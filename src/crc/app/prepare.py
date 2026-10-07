"""Prepare les donnees du tableau de bord (mode rejeu sur decembre 2024).

    python -m crc.app.prepare

Le tableau de bord rejoue un mois reel jour par jour : pour chaque journee, il montre ce que
la plateforme aurait annonce LA VEILLE (prevision, risque, planning optimal, alertes), puis
ce qui s'est reellement passe. Les calculs lourds sont faits une fois ici et sauvegardes
dans data/app/ ; le tableau de bord ne fait que les lire (sauf le what-if, calcule a la demande).
"""
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from crc.forecasting.anomalies import AnomalyDetector
from crc.forecasting.ml import HybridForecaster
from crc.forecasting.registry import aht_forecast
from crc.optim.staffing import build_curves, deterministic_plan, evaluate_plan, risk_aware_plan
from crc.optim.whatif import ALPHA
from crc.app.alerts import build_alerts, interval_levels
from crc.risk.costs import load_costs
from crc.risk.report import build_risk_model
from crc.risk.simulation import expected_shortfall, var

APP_DIR = Path("data/app")
REPLAY_START, REPLAY_END = pd.Timestamp("2024-12-01"), pd.Timestamp("2025-01-01")
N_SCENARIOS = 1000


def run() -> None:
    from crc.forecasting.compare import load_inputs
    from crc.forecasting.intervals import rolling_forecast

    t0 = time.perf_counter()
    APP_DIR.mkdir(parents=True, exist_ok=True)
    df, events, X = load_inputs()
    costs = load_costs()

    print("Previsions hors echantillon des 12 derniers mois...")
    mu_all = rolling_forecast(df, events, X, REPLAY_START - pd.DateOffset(months=12), REPLAY_END)
    model = build_risk_model(df, mu_all, costs, calib_end=REPLAY_START, history=df[df.index < REPLAY_START])
    hybrid = HybridForecaster().fit(df, X, events, REPLAY_START)
    aht = aht_forecast(df)

    win = slice(REPLAY_START, REPLAY_END - pd.Timedelta(minutes=30))
    mu, y = mu_all.loc[win], df.loc[win, "offered"].astype(float)
    dates = pd.Series(mu.index.date, index=mu.index)
    q = model.predictive.quantiles(mu, dates, (0.01, 0.1, 0.5, 0.9, 0.99))
    anomalies = AnomalyDetector(model.predictive).detect(mu, y, dates)

    print("Risque et planning optimal, jour par jour...")
    day_rows, interval_parts, alert_parts, losses = [], [], [], {}
    absence_mean = float(model.absence_rates.mean())
    absence_real = (df["agents_absent"].groupby(df["date"]).sum()
                    / df["agents_scheduled"].groupby(df["date"]).sum())
    for day in pd.date_range(REPLAY_START, REPLAY_END - pd.Timedelta(days=1), freq="D"):
        sl = slice(day, day + pd.Timedelta(hours=23.5))
        m, a = mu.loc[sl], aht.loc[sl]
        baseline = df.loc[sl, "agents_scheduled"].to_numpy()
        ia = deterministic_plan(m, a, absence_mean, model.patience, costs)
        optimal = risk_aware_plan(build_curves(model, m, a, ia, 100, seed=day.dayofyear), costs, ALPHA)

        sims = {k: model.simulate(m, a, p, n=N_SCENARIOS, seed=day.dayofyear)
                for k, p in (("baseline", baseline), ("optimise", optimal))}
        p_under = pd.Series(sims["baseline"]["sous_capacite"].mean(axis=0), index=m.index)
        exp_loss = pd.Series(sims["baseline"]["perte"].mean(axis=0), index=m.index)
        level = interval_levels(p_under, anomalies.loc[sl, "niveau"])
        alerts = build_alerts(level, p_under, exp_loss, pd.Series(baseline, index=m.index),
                              pd.Series(optimal, index=m.index))
        alerts.insert(0, "jour", day)
        alert_parts.append(alerts)

        absence = pd.Series(absence_real.loc[day.date()], index=m.index)
        row = {"jour": day}
        for key, plan in (("baseline", baseline), ("optimise", optimal)):
            daily = sims[key]["perte"].sum(axis=1)
            losses[f"{key}_{day:%Y%m%d}"] = daily
            real = evaluate_plan(plan, df.loc[sl, "offered"], df.loc[sl, "avg_handle_seconds"], absence,
                                 model.patience, costs)
            row.update({
                f"{key}_cout_agents": float(real["cout_agents"].sum()),
                f"{key}_perte_attendue": float(daily.mean()),
                f"{key}_VaR95": var(daily, 0.95), f"{key}_ES95": expected_shortfall(daily, 0.95),
                f"{key}_perte_reelle": float(real["perte"].sum()),
                f"{key}_sl_reel": float((real["sl"] * real["appels"]).sum() / max(real["appels"].sum(), 1)),
            })
        row["niveau_max"] = int(level.max())
        day_rows.append(row)

        interval_parts.append(pd.DataFrame({
            "agents_baseline": baseline, "agents_ia": ia, "agents_optimise": optimal,
            "p_sous_capacite_baseline": p_under,
            "p_sous_capacite_optimise": sims["optimise"]["sous_capacite"].mean(axis=0),
            "perte_attendue_baseline": exp_loss, "niveau_alerte": level,
        }, index=m.index))

    intervals = pd.concat(interval_parts).join(pd.DataFrame({
        "volume_prevu": mu, "q01": q[0.01], "q10": q[0.1], "q90": q[0.9], "q99": q[0.99],
        "aht_prevue": aht.loc[win], "volume_observe": y, "anomalie": anomalies["niveau"],
    }))
    intervals.to_parquet(APP_DIR / "intervalles.parquet")
    pd.DataFrame(day_rows).set_index("jour").to_parquet(APP_DIR / "jours.parquet")
    pd.concat(alert_parts, ignore_index=True).to_parquet(APP_DIR / "alertes.parquet")
    np.savez_compressed(APP_DIR / "pertes_scenarios.npz", **losses)
    joblib.dump({"risk_model": model, "hybrid": hybrid, "mu": mu, "aht": aht.loc[win], "X": X.loc[win]},
                APP_DIR / "modeles.joblib")
    print(f"Donnees du tableau de bord pretes dans {APP_DIR} ({time.perf_counter() - t0:.0f} s)")


if __name__ == "__main__":
    run()