"""Ce que la plateforme annonce pour demain : prevision, plannings, risque, alertes.

Tout est calcule avec le modele en service (ForecastBundle) et l'historique disponible
jusqu'a la veille. Aucune information du jour prevu n'est utilisee.
"""
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from crc.app.alerts import build_alerts, interval_levels
from crc.app.explain import contributions
from crc.forecasting.features import build_features
from crc.forecasting.registry import ForecastBundle, future_frame
from crc.optim.shifts import ShiftSolution, schedule_shifts
from crc.optim.staffing import build_curves, deterministic_plan, risk_aware_plan
from crc.risk.costs import INTERVAL_SECONDS, estimate_patience
from crc.forecasting.statistical import daily_level
from crc.risk.simulation import OperationalRiskModel, expected_shortfall, var

QUANTILES = (0.01, 0.1, 0.5, 0.9, 0.99)
N_SCENARIOS = 1000
OFFSETS = np.arange(-3, 13)          # effectifs candidats : assez larges pour que les vacations puissent deborder


@dataclass
class PlanOutlook:
    agents: pd.Series                  # agents planifies par demi-heure
    undercap: pd.Series                # probabilite de sous-capacite
    expected_loss: pd.Series           # perte attendue par demi-heure (EUR)
    service_level: pd.Series           # service level attendu
    summary: dict                      # synthese de la journee


@dataclass
class DayOutlook:
    day: date
    forecast: pd.DataFrame             # attendu, quantiles, AHT
    plans: dict                        # "actuel", "recommande" -> PlanOutlook
    alerts: pd.DataFrame
    shifts: ShiftSolution              # vacations du planning recommande
    ideal: PlanOutlook                 # besoin demi-heure par demi-heure, sans contrainte de vacation
    model: OperationalRiskModel        # modele de risque utilise (reutilise pour les ajustements)


def risk_model_for(bundle: ForecastBundle, history: pd.DataFrame, costs: dict) -> OperationalRiskModel:
    """Incertitude du modele en service, absences et patience estimees sur l'historique."""
    absence = (history["agents_absent"].groupby(history["date"]).sum()
               / history["agents_scheduled"].groupby(history["date"]).sum()).to_numpy()
    recent = history[history.index >= history.index[-1] - pd.Timedelta(days=365)]
    return OperationalRiskModel(bundle.predictive, absence, estimate_patience(recent), costs)


def forecast_day(bundle: ForecastBundle, history: pd.DataFrame, events: pd.DataFrame, day: date) -> pd.DataFrame:
    """Prevision du jour `day` (le lendemain de la derniere donnee), avec son explication.

    Colonnes : attendu, aht, quantiles, niveau_jour (total journalier du SARIMAX) et, pour
    chaque facteur, son effet en % sur la demi-heure (valeurs de SHAP de la partie LightGBM).
    """
    extended = future_frame(history, days=1)
    X = build_features(extended, events)
    fc = bundle.forecast(extended, events, X)
    fc = fc[fc.index.date == day]
    q = bundle.predictive.quantiles(fc["volume_attendu"], pd.Series(fc.index.date, index=fc.index), QUANTILES)
    q.columns = ["q01", "q10", "q50", "q90", "q99"]
    level = daily_level(extended, events, params=bundle.hybrid.sarimax_params).reindex(fc.index)
    effects = contributions(bundle.hybrid, X.loc[fc.index]).add_prefix("effet:")
    return pd.concat([fc.rename(columns={"volume_attendu": "attendu", "aht_attendue": "aht"}), q,
                      (level * len(fc)).rename("niveau_jour"), effects], axis=1)


def evaluate_plan(model: OperationalRiskModel, forecast: pd.DataFrame, agents, seed: int) -> PlanOutlook:
    mu, aht = forecast["attendu"], forecast["aht"]
    sim = model.simulate(mu, aht, np.asarray(agents), n=N_SCENARIOS, seed=seed)
    daily = sim["perte"].sum(axis=1)
    weights = sim["arrivees"] + 1e-9
    sl = (sim["service_level"] * weights).sum(axis=0) / weights.sum(axis=0)
    agents = pd.Series(np.asarray(agents, dtype=int), index=mu.index)
    cost = model.costs["cost_agent_hour"] * INTERVAL_SECONDS / 3600 * agents.sum()
    return PlanOutlook(
        agents=agents,
        undercap=pd.Series(sim["sous_capacite"].mean(axis=0), index=mu.index),
        expected_loss=pd.Series(sim["perte"].mean(axis=0), index=mu.index),
        service_level=pd.Series(sl, index=mu.index),
        summary={
            "agent_hours": float(agents.sum() / 2), "cost_agents": float(cost),
            "expected_loss": float(daily.mean()), "var95": var(daily, 0.95), "es95": expected_shortfall(daily, 0.95),
            "expected_service_level": float(np.average(sim["service_level"], weights=weights)),
            "max_undercap_probability": float(sim["sous_capacite"].mean(axis=0).max()),
        },
    )


def compute_outlook(bundle: ForecastBundle, history: pd.DataFrame, events: pd.DataFrame, day: date,
                    current_plan: pd.Series, costs: dict) -> DayOutlook:
    """Prevision, planning actuel vs recommande, risque et alertes pour le jour `day`."""
    forecast = forecast_day(bundle, history, events, day)
    model = risk_model_for(bundle, history, costs)
    mu, aht = forecast["attendu"], forecast["aht"]
    seed = int(pd.Timestamp(day).strftime("%Y%m%d"))

    alpha = costs.get("risk_alpha", 0.05)
    center = deterministic_plan(mu, aht, float(model.absence_rates.mean()), model.patience, costs)
    curves = build_curves(model, mu, aht, center, 100, seed=seed, offsets=OFFSETS)
    need = risk_aware_plan(curves, costs, alpha)                  # optimum demi-heure par demi-heure
    shifts = schedule_shifts(curves, costs, alpha)                # traduit en vacations reelles
    actual = current_plan.reindex(mu.index).ffill().bfill().astype(int).to_numpy()

    plans = {"actuel": evaluate_plan(model, forecast, actual, seed),
             "recommande": evaluate_plan(model, forecast, shifts.coverage, seed)}
    ideal = evaluate_plan(model, forecast, need, seed)
    level = interval_levels(plans["actuel"].undercap, high=costs.get("alert_high_threshold", 0.20),
                            medium=costs.get("alert_medium_threshold", 0.10))
    alerts = build_alerts(level, plans["actuel"].undercap, plans["actuel"].expected_loss,
                          plans["actuel"].agents, plans["recommande"].agents)
    return DayOutlook(day, forecast, plans, alerts, shifts, ideal, model)


def detect_anomalies(bundle: ForecastBundle, expected: pd.Series, observed: pd.Series) -> pd.DataFrame:
    """Compare la journee realisee a ce qui avait ete prevu la veille."""
    dates = pd.Series(expected.index.date, index=expected.index)
    return bundle.detector().detect(expected, observed.reindex(expected.index).astype(float), dates)
