"""Le prix des vacations : combien coute le passage du besoin ideal a des vacations reelles ?

    python -m crc.optim.shifts_report

Sur une semaine de la validation, on compare trois organisations du travail :
  souple    : debut toutes les 30 min, 4/6/8 h, aucun cout de lisibilite
  standard  : debut a l'heure pile, 4/6/8 h, 30 EUR par type de vacation (regle retenue)
  rigide    : debut a l'heure pile, uniquement des journees de 8 h
Chaque solution est evaluee par Monte Carlo, comme le besoin ideal demi-heure par demi-heure.
"""
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from crc.forecasting.registry import aht_forecast
from crc.ops.outlook import OFFSETS
from crc.optim.shifts import PATTERN_COST, schedule_shifts, shifts_frame
from crc.optim.staffing import build_curves, deterministic_plan, risk_aware_plan
from crc.risk.costs import INTERVAL_SECONDS, load_costs
from crc.risk.report import build_risk_model

WEEK = pd.date_range("2024-03-11", periods=7, freq="D")
RULES = {
    "souple": dict(start_step=1, pattern_cost=0.0, lengths=None),
    "standard": dict(start_step=2, pattern_cost=PATTERN_COST, lengths=None),
    "rigide": dict(start_step=2, pattern_cost=PATTERN_COST, lengths=[8]),
}
OUT = Path("outputs")
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def expected_total(model, mu, aht, plan, seed) -> float:
    sim = model.simulate(mu, aht, plan, n=1000, seed=seed)
    staff = model.costs["cost_agent_hour"] * INTERVAL_SECONDS / 3600 * np.asarray(plan).sum()
    return float(staff + sim["perte"].sum(axis=1).mean())


def run() -> pd.DataFrame:
    from crc.forecasting.compare import load_inputs
    from crc.forecasting.intervals import rolling_forecast

    t0 = time.perf_counter()
    df, events, X = load_inputs()
    costs = load_costs()
    mu = rolling_forecast(df, events, X, pd.Timestamp("2023-07-01"), pd.Timestamp("2024-04-01"))
    model = build_risk_model(df, mu, costs)
    aht = aht_forecast(df)
    alpha = costs.get("risk_alpha", 0.05)

    rows, example = [], None
    for day in WEEK:
        sl = slice(day, day + pd.Timedelta(hours=23.5))
        m, a = mu.loc[sl], aht.loc[sl]
        seed = int(day.strftime("%Y%m%d"))
        center = deterministic_plan(m, a, float(model.absence_rates.mean()), model.patience, costs)
        curves = build_curves(model, m, a, center, 100, seed=seed, offsets=OFFSETS)
        need = risk_aware_plan(curves, costs, alpha)
        ideal = expected_total(model, m, a, need, seed)
        for rule, kw in RULES.items():
            sol = schedule_shifts(curves, costs, alpha, **kw)
            total = expected_total(model, m, a, sol.coverage, seed)
            rows.append({"jour": f"{JOURS[day.dayofweek]} {day:%d/%m}", "regle": rule, "types de vacations": len(sol.shifts),
                         "agents": int(sol.shifts["agents"].sum()), "heures payees": sol.paid_hours,
                         "heures ideales": need.sum() / 2, "prix des vacations %": 100 * (total - ideal) / ideal,
                         "ecart optimum %": 100 * sol.gap, "calcul s": sol.solve_seconds})
            if rule == "standard" and day == WEEK[0]:
                example = (day, need, sol)
        print(f"  {day:%d/%m} termine")

    res = pd.DataFrame(rows)
    summary = res.groupby("regle", sort=False)[["types de vacations", "heures payees", "heures ideales",
                                                "prix des vacations %", "ecart optimum %", "calcul s"]].mean().round(2)
    OUT.mkdir(exist_ok=True)
    res.round(2).to_csv(OUT / "vacations_par_jour.csv", index=False)
    summary.to_csv(OUT / "vacations_resume.csv")
    _figure(*example)
    print(f"\nPrix des vacations sur la semaine du 11 mars 2024 ({time.perf_counter() - t0:.0f} s) :\n")
    print(summary.to_string())
    return summary


def _figure(day, need, sol) -> None:
    idx = pd.date_range(day, periods=48, freq="30min")
    frame = shifts_frame(sol, day)
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [1, 1.3]})
    a1.step(idx, need, where="post", color="grey", lw=2, label="besoin ideal (demi-heure par demi-heure)")
    a1.step(idx, sol.coverage, where="post", color="C2", lw=2, label="couverture par les vacations")
    a1.fill_between(idx, need, sol.coverage, step="post", color="C2", alpha=0.15)
    a1.set(ylabel="agents", title=f"Du besoin aux vacations : {JOURS[day.dayofweek]} {day:%d/%m/%Y}")
    a1.legend(fontsize=8)
    for i, r in enumerate(frame.itertuples()):
        start, end = r.debut, r.fin
        a2.barh(i, (end - start) / pd.Timedelta(hours=1) / 24, left=matplotlib.dates.date2num(start),
                height=0.7, color="C0")
        a2.text(matplotlib.dates.date2num(start) + 0.005, i, f"{r.agents} ag. - {r.duree_h:.0f} h",
                va="center", fontsize=7, color="white")
    a2.set(yticks=[], title=f"{len(frame)} types de vacations, {int(frame['agents'].sum())} agents")
    a2.invert_yaxis()
    a2.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%Hh"))
    a2.set_xlim(idx[0], idx[-1] + pd.Timedelta(hours=8))
    fig.tight_layout()
    (OUT / "figures").mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "figures" / "19_vacations.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    run()
