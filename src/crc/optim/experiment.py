"""Experience finale (section 28 du document de cadrage).

    python -m crc.optim.experiment

Trois strategies de planification comparees sur la periode de TEST (juillet - decembre 2024),
evaluee ici pour la premiere et unique fois :
  1. Baseline               : le planning reellement applique (Erlang C sur une prevision naive)
  2. IA                     : prevision du champion + Erlang A, sans tenir compte de l'incertitude
  3. IA + actuariat + optim : Monte Carlo + cout total minimal sous contrainte de risque
Toutes sont jugees avec le meme moteur (Erlang A), face a la demande et aux absences REELLES.
"""
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from crc.forecasting.registry import aht_forecast
from crc.optim.staffing import build_curves, deterministic_plan, evaluate_plan, risk_aware_plan
from crc.risk.costs import load_costs
from crc.risk.report import build_risk_model
from crc.splits import SPLITS, select

TEST_START, TEST_END = SPLITS["test"]
CALIB_START = TEST_START - pd.DateOffset(months=12)
ALPHA = 0.05                 # P(sous-capacite) maximale, choisie sur la validation
FRONTIER = (1.01, 0.10, 0.05, 0.02)
N_SCENARIOS = 100
OUT = Path("outputs")
NAMES = {"baseline": "1. Baseline", "ia": "2. IA", "risque": "3. IA + actuariat + optimisation"}


def daily_absence(df: pd.DataFrame) -> pd.Series:
    return df["agents_absent"].groupby(df["date"]).sum() / df["agents_scheduled"].groupby(df["date"]).sum()


def plan_test_period(df, mu, aht, model, costs):
    """Plannings des trois strategies, jour par jour, avec les seules informations de la veille."""
    plans = {k: [] for k in ("baseline", "ia", *[f"alpha_{a}" for a in FRONTIER])}
    absence_mean = float(model.absence_rates.mean())
    days = pd.date_range(TEST_START, TEST_END - pd.Timedelta(days=1), freq="D")
    for i, day in enumerate(days):
        sl = slice(day, day + pd.Timedelta(hours=23.5))
        m, a = mu.loc[sl], aht.loc[sl]
        ia = deterministic_plan(m, a, absence_mean, model.patience, costs)
        curves = build_curves(model, m, a, ia, N_SCENARIOS, seed=day.dayofyear)
        plans["baseline"].append(pd.Series(df.loc[sl, "agents_scheduled"].to_numpy(), index=m.index))
        plans["ia"].append(pd.Series(ia, index=m.index))
        for alpha in FRONTIER:
            plans[f"alpha_{alpha}"].append(pd.Series(risk_aware_plan(curves, costs, alpha), index=m.index))
        if (i + 1) % 30 == 0:
            print(f"  {i + 1}/{len(days)} jours planifies")
    plans = {k: pd.concat(v) for k, v in plans.items()}
    plans["risque"] = plans[f"alpha_{ALPHA}"]
    return plans


def score(e: pd.DataFrame) -> dict:
    daily_loss = e["perte"].groupby(e.index.date).sum()
    worst = daily_loss.sort_values().iloc[-max(1, round(0.05 * len(daily_loss))):]
    return {
        "cout total EUR": (e["cout_agents"] + e["perte"]).sum(),
        "cout agents EUR": e["cout_agents"].sum(),
        "perte operationnelle EUR": e["perte"].sum(),
        "service level %": 100 * (e["sl"] * e["appels"]).sum() / e["appels"].sum(),
        "abandon %": 100 * e["abandons"].sum() / e["appels"].sum(),
        "sous-capacite % intervalles": 100 * e["sous_capacite"].mean(),
        "perte attendue / jour EUR": daily_loss.mean(),
        "ES95 / jour EUR": worst.mean(),          # moyenne des 5 % pires journees
    }


def forecast_accuracy(df, mu, model) -> dict:
    """DSO1 sur le test, mesure une seule fois."""
    idx = mu.loc[TEST_START:TEST_END - pd.Timedelta(minutes=30)].index
    ok = ~df.loc[idx, "is_imputed"].to_numpy()
    y, m = df.loc[idx, "offered"].astype(float)[ok], mu.loc[idx][ok]
    q = model.predictive.quantiles(m, pd.Series(m.index.date, index=m.index), (0.1, 0.9))
    return {"WAPE %": 100 * (m - y).abs().sum() / y.sum(), "biais %": 100 * (m - y).sum() / y.sum(),
            "couverture fourchette 80 %": 100 * ((y >= q[0.1]) & (y <= q[0.9])).mean()}


def run() -> pd.DataFrame:
    from crc.forecasting.compare import load_inputs
    from crc.forecasting.intervals import rolling_forecast

    t0 = time.perf_counter()
    OUT.mkdir(exist_ok=True)
    df, events, X = load_inputs()
    costs = load_costs()
    print("Previsions hors echantillon (reentrainement mensuel)...")
    mu = rolling_forecast(df, events, X, CALIB_START, TEST_END)
    model = build_risk_model(df, mu, costs, calib_end=TEST_START, history=select(df, "train", "validation"))
    aht = aht_forecast(df)

    print("Planification de la periode de test...")
    plans = plan_test_period(df, mu, aht, model, costs)

    idx = plans["baseline"].index
    absence = pd.Series(df.loc[idx, "date"].map(daily_absence(df)).to_numpy(), index=idx)
    actual = dict(offered=df.loc[idx, "offered"], aht=df.loc[idx, "avg_handle_seconds"], absence_rate=absence,
                  patience=model.patience, costs=costs)
    evals = {k: evaluate_plan(p, **actual) for k, p in plans.items()}

    table = pd.DataFrame({NAMES[k]: score(evals[k]) for k in NAMES}).T
    table.insert(0, "indice de cout", 100 * table["cout total EUR"] / table.loc[NAMES["baseline"], "cout total EUR"])
    frontier = pd.DataFrame({("sans contrainte" if a > 1 else f"alpha = {a:.0%}"): score(evals[f"alpha_{a}"])
                             for a in FRONTIER}).T
    frontier.insert(0, "indice de cout",
                    100 * frontier["cout total EUR"] / table.loc[NAMES["baseline"], "cout total EUR"])
    accuracy = forecast_accuracy(df, mu, model)

    table.round(2).to_csv(OUT / "experience_finale.csv")
    frontier.round(2).to_csv(OUT / "frontiere_cout_risque.csv")
    pd.Series(accuracy).round(2).to_csv(OUT / "precision_test.csv", header=["valeur"])
    _figures(table, frontier, plans, mu, df)

    pd.set_option("display.width", 250)
    print("\nPrecision de la prevision sur le test (mesuree une seule fois) :")
    for k, v in accuracy.items():
        print(f"  {k:<28} {v:6.2f}")
    print("\nEXPERIENCE FINALE - periode de test (juillet - decembre 2024) :\n")
    print(table.round(1).to_string())
    print("\nFrontiere cout / risque de la strategie 3 :\n")
    print(frontier[["indice de cout", "service level %", "sous-capacite % intervalles", "ES95 / jour EUR"]]
          .round(1).to_string())
    print(f"\nTermine en {time.perf_counter() - t0:.0f} s")
    return table


def _figures(table, frontier, plans, mu, df) -> None:
    fig_dir = OUT / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    cols = ["indice de cout", "service level %", "abandon %", "sous-capacite % intervalles"]
    fig, axes = plt.subplots(1, 4, figsize=(14, 3.8))
    for ax, col in zip(axes, cols):
        ax.bar(range(3), table[col], color=["grey", "C0", "C2"])
        ax.set_xticks(range(3), ["Baseline", "IA", "IA + risque"])
        ax.set_title(col)
        for i, v in enumerate(table[col]):
            ax.text(i, v, f"{v:.1f}", ha="center", va="bottom", fontsize=9)
    fig.suptitle("Experience finale sur la periode de test (juillet - decembre 2024)")
    fig.tight_layout()
    fig.savefig(fig_dir / "16_experience_finale.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(frontier["ES95 / jour EUR"], frontier["indice de cout"], marker="o", color="C2",
            label="strategie 3 (alpha variable)")
    for name, row in frontier.iterrows():
        ax.annotate(name, (row["ES95 / jour EUR"], row["indice de cout"]), textcoords="offset points",
                    xytext=(5, 5), fontsize=8)
    for name, color in ((NAMES["baseline"], "grey"), (NAMES["ia"], "C0")):
        ax.scatter(table.loc[name, "ES95 / jour EUR"], table.loc[name, "indice de cout"], s=80,
                   color=color, label=name)
    ax.set(xlabel="perte moyenne des 5 % pires journees (EUR)", ylabel="cout total (base 100 = Baseline)",
           title="Frontiere cout / risque")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(fig_dir / "17_frontiere_cout_risque.png", dpi=150)
    plt.close(fig)

    day = pd.Timestamp("2024-09-16")
    sl = slice(day, day + pd.Timedelta(hours=23.5))
    fig, ax1 = plt.subplots(figsize=(11, 4.2))
    ax1.fill_between(mu.loc[sl].index, 0, mu.loc[sl], color="grey", alpha=0.2, label="volume prevu")
    ax1.set_ylabel("appels prevus / 30 min")
    ax2 = ax1.twinx()
    for key, color in (("baseline", "grey"), ("ia", "C0"), ("risque", "C2")):
        ax2.step(plans[key].loc[sl].index, plans[key].loc[sl], where="post", color=color, lw=2,
                 label=NAMES[key])
    ax2.set_ylabel("agents planifies")
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, fontsize=8, loc="upper left")
    ax1.set_title("Plannings du lundi 16 septembre 2024 (rentree)")
    fig.tight_layout()
    fig.savefig(fig_dir / "18_plannings_jour.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    run()