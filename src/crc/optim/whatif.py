"""Analyse what-if (module 16) : le manager change une hypothese, le systeme recalcule tout.

    python -m crc.optim.whatif

Questions types du document de cadrage :
  "Que se passe-t-il si le volume augmente de 20 % ?"     -> Scenario(volume_factor=1.2)
  "Que se passe-t-il si 10 % des agents sont absents ?"   -> Scenario(extra_absence=0.10)
  "Je veux reduire mon cout de 15 %."                     -> Scenario(budget_cut=0.15)
"""
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from crc.optim.staffing import (budget_plan, build_curves, deterministic_plan, risk_aware_plan,
                                staff_cost)
from crc.risk.simulation import OperationalRiskModel

ALPHA = 0.05
WIDE_OFFSETS = np.arange(-10, 9)        # plage elargie pour pouvoir descendre sous un budget


@dataclass
class Scenario:
    volume_factor: float = 1.0          # 1.2 = +20 % d'appels
    extra_absence: float = 0.0          # 0.10 = 10 points d'absence en plus
    budget_cut: float | None = None     # 0.15 = budget agents reduit de 15 %
    alpha: float = ALPHA


def what_if(model: OperationalRiskModel, mu: pd.Series, aht: pd.Series, scenario: Scenario,
            n_scenarios: int = 100, seed: int = 0) -> dict:
    """Planning recommande et ses consequences (cout, pertes, VaR, service level) sous le scenario."""
    m = mu * scenario.volume_factor
    stressed = replace(model, absence_rates=np.clip(model.absence_rates + scenario.extra_absence, 0, 0.9))
    center = deterministic_plan(m, aht, float(stressed.absence_rates.mean()), model.patience, model.costs)
    curves = build_curves(stressed, m, aht, center, n_scenarios, seed, offsets=WIDE_OFFSETS)
    plan = risk_aware_plan(curves, model.costs, scenario.alpha)
    note = None
    if scenario.budget_cut:
        budget = (1 - scenario.budget_cut) * staff_cost(plan, model.costs).sum()
        plan = budget_plan(curves, budget)
        if staff_cost(plan, model.costs).sum() > budget + 1e-6:
            note = "budget inatteignable dans la plage d'effectifs etudiee"
    risk = stressed.day_risk(m, aht, plan, n=1000, seed=seed)
    worst = int(np.argmax(risk["proba_sous_capacite"]))
    return {
        "plan": pd.Series(plan, index=mu.index, name="agents"),
        "heures_agents": plan.sum() / 2,
        "cout_agents": risk["cout_agents"],
        "perte_attendue": risk["perte_attendue"],
        "cout_total_attendu": risk["cout_agents"] + risk["perte_attendue"],
        "VaR95": risk["VaR95"], "ES95": risk["ES95"],
        "service_level_attendu": risk["service_level_attendu"],
        "proba_sous_capacite_max": float(risk["proba_sous_capacite"][worst]),
        "intervalle_le_plus_risque": mu.index[worst],
        "remarque": note,
    }


def compare(model, mu, aht, scenarios: dict[str, Scenario], seed: int = 0) -> pd.DataFrame:
    """Tableau de synthese : une ligne par scenario."""
    rows = {}
    for name, sc in scenarios.items():
        r = what_if(model, mu, aht, sc, seed=seed)
        rows[name] = {k: v for k, v in r.items() if k != "plan"}
    return pd.DataFrame(rows).T


def run(day: str = "2024-03-11") -> pd.DataFrame:
    from crc.forecasting.compare import load_inputs
    from crc.forecasting.intervals import rolling_forecast
    from crc.forecasting.registry import aht_forecast
    from crc.risk.costs import load_costs
    from crc.risk.report import build_risk_model

    df, events, X = load_inputs()
    d = pd.Timestamp(day)
    start = (d - pd.DateOffset(months=6)).replace(day=1)
    mu = rolling_forecast(df, events, X, start, (d + pd.DateOffset(months=1)).replace(day=1))
    model = build_risk_model(df, mu, load_costs(), calib_end=d.replace(day=1))
    sl = slice(d, d + pd.Timedelta(hours=23.5))
    table = compare(model, mu.loc[sl], aht_forecast(df).loc[sl], {
        "Reference": Scenario(),
        "Volume +20 %": Scenario(volume_factor=1.2),
        "Absences +10 points": Scenario(extra_absence=0.10),
        "Budget agents -15 %": Scenario(budget_cut=0.15),
    })
    cols = ["heures_agents", "cout_agents", "perte_attendue", "cout_total_attendu", "ES95",
            "service_level_attendu", "proba_sous_capacite_max", "remarque"]
    pd.set_option("display.width", 250)
    print(f"What-if pour le {d:%d/%m/%Y} :\n")
    print(table[cols].to_string())
    return table


if __name__ == "__main__":
    run()