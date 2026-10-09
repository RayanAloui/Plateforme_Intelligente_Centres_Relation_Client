"""Capacite et recrutement : combien d'agents faudra-t-il dans 3, 12 ou 36 mois ?

Ce n'est plus la question de demain (planning) mais celle du directeur de centre (budget,
recrutement). On travaille donc au mois :

  1. volume journalier moyen de chaque mois  -> SARIMA "airline" (0,1,1)(0,1,1)12 en logarithme
     (le nombre de jours du mois est connu : volume du mois = moyenne journaliere x jours)
  2. fourchettes qui s'elargissent avec l'horizon (intervalles de prevision du modele)
  3. fiabilite MESUREE : erreur reelle du modele a 1, 3, 6 et 12 mois sur l'historique
  4. traduction en heures d'agents, equivalents temps plein (ETP) et budget
"""
import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX

ORDER, SEASONAL = (0, 1, 1), (0, 1, 1, 12)
PAID_HOURS_PER_FTE = 35 * 52 / 12            # 151,7 h payees par mois pour un temps plein
HORIZONS = (1, 3, 6, 12)


def monthly_series(history: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par mois COMPLET : volume total, nombre de jours, moyenne journaliere."""
    daily = history["offered"].groupby(history.index.normalize()).sum()
    months = daily.groupby(daily.index.to_period("M")).agg(["sum", "count"])
    months.columns = ["total", "days"]
    months = months[months["days"] == months.index.days_in_month]
    months.index = months.index.to_timestamp()
    months["daily_mean"] = months["total"] / months["days"]
    return months


def _fit(y: pd.Series):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return SARIMAX(np.log(y), order=ORDER, seasonal_order=SEASONAL).fit(disp=False)


def forecast_months(monthly: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Volume prevu de chaque mois futur : mediane et fourchettes a 80 % et 95 %."""
    y = monthly["daily_mean"].asfreq("MS")
    res = _fit(y)
    fc = res.get_forecast(horizon)
    out = pd.DataFrame(index=fc.predicted_mean.index)
    days = out.index.days_in_month
    out["jours"] = days
    out["p50"] = np.exp(fc.predicted_mean) * days
    for alpha, lo, hi in ((0.2, "p10", "p90"), (0.05, "p025", "p975")):
        ci = fc.conf_int(alpha=alpha)
        out[lo], out[hi] = np.exp(ci.iloc[:, 0]) * days, np.exp(ci.iloc[:, 1]) * days
    return out


def backtest(monthly: pd.DataFrame, horizons=HORIZONS, min_train: int = 24) -> pd.DataFrame:
    """Erreur reelle du modele selon l'horizon : on se place a chaque mois passe, on prevoit,
    puis on compare a ce qui s'est produit."""
    y = monthly["daily_mean"].asfreq("MS")
    rows = []
    for origin in range(min_train, len(y)):
        res = _fit(y.iloc[:origin])
        fc = res.get_forecast(max(horizons))
        ci = fc.conf_int(alpha=0.2)
        for h in horizons:
            if origin + h - 1 < len(y):
                actual = y.iloc[origin + h - 1]
                pred = float(np.exp(fc.predicted_mean.iloc[h - 1]))
                lo, hi = np.exp(ci.iloc[h - 1, 0]), np.exp(ci.iloc[h - 1, 1])
                rows.append({"horizon": h, "erreur": abs(pred - actual) / actual, "dans_80": lo <= actual <= hi})
    res = pd.DataFrame(rows)
    if res.empty:
        return pd.DataFrame(columns=["erreur_moyenne_pct", "couverture_80_pct", "essais"])
    return res.groupby("horizon").agg(erreur_moyenne_pct=("erreur", lambda e: 100 * e.mean()),
                                      couverture_80_pct=("dans_80", lambda c: 100 * c.mean()),
                                      essais=("erreur", "size"))


def capacity_plan(forecast: pd.DataFrame, hours_per_call: float, absence_rate: float,
                  cost_agent_hour: float) -> pd.DataFrame:
    """Heures d'agents, ETP (absences incluses) et budget pour chaque mois et chaque quantile."""
    out = forecast.copy()
    for q in ("p10", "p50", "p90"):
        hours = out[q] * hours_per_call
        out[f"heures_{q}"] = hours
        out[f"etp_{q}"] = hours / PAID_HOURS_PER_FTE / (1 - absence_rate)
        out[f"budget_{q}"] = hours * cost_agent_hour
    return out


def staffing_ratio(history: pd.DataFrame, days: int = 365) -> float:
    """Heures d'agents planifiees par appel sur la periode recente (reference si aucun planning
    recommande n'est encore disponible)."""
    recent = history[history.index >= history.index[-1] - pd.Timedelta(days=days)]
    return float(0.5 * recent["agents_scheduled"].sum() / recent["offered"].sum())
