"""Phase 3 : le risque operationnel en euros, en une commande.

    python -m crc.risk.report

1. Approche actuarielle frequence x severite sur l'historique (six risques)
2. Monte Carlo prospectif journee par journee, et backtest de la VaR sur la validation
"""
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from crc.forecasting.probabilistic import CoxPredictive
from crc.forecasting.registry import aht_forecast
from crc.risk.costs import estimate_patience, load_costs, observed_losses
from crc.risk.lda import SEVERITY_LAWS, lda_table
from crc.risk.simulation import OperationalRiskModel, kupiec_test
from crc.splits import SPLITS, select

OUT = Path("outputs")
START, CALIB_END, END = pd.Timestamp("2023-07-01"), SPLITS["validation"][0], SPLITS["test"][0]
N_SCENARIOS = 500


def build_risk_model(df, mu, costs) -> OperationalRiskModel:
    """Assemble le modele de risque : incertitude de la demande, absences, patience."""
    y = df.loc[mu.index, "offered"].astype(float)
    dates = pd.Series(df.loc[mu.index, "date"].to_numpy(), index=mu.index)
    calib = ~df.loc[mu.index, "is_imputed"].to_numpy() & (mu.index < CALIB_END)
    predictive = CoxPredictive.calibrate(mu[calib], y[calib], dates[calib])
    train = select(df, "train")
    absence = (train["agents_absent"].groupby(train["date"]).sum()
               / train["agents_scheduled"].groupby(train["date"]).sum()).to_numpy()
    return OperationalRiskModel(predictive, absence, estimate_patience(train), costs)


def backtest_var(df, mu, model, costs) -> pd.DataFrame:
    """Chaque jour de la validation : VaR prevue la veille vs perte reellement subie."""
    realized = observed_losses(df, costs)["perte"]
    aht = aht_forecast(df)
    rows = []
    for day in pd.date_range(CALIB_END, END - pd.Timedelta(days=1), freq="D"):
        sl = slice(day, day + pd.Timedelta(hours=23.5))
        r = model.day_risk(mu.loc[sl], aht.loc[sl], df.loc[sl, "agents_scheduled"].to_numpy(),
                           n=N_SCENARIOS, seed=day.dayofyear)
        rows.append({"jour": day, "perte_reelle": realized.loc[sl].sum(), "perte_attendue": r["perte_attendue"],
                     "VaR95": r["VaR95"], "ES95": r["ES95"], "VaR99": r["VaR99"], "ES99": r["ES99"]})
    return pd.DataFrame(rows).set_index("jour")


def run() -> None:
    from crc.forecasting.compare import load_inputs
    from crc.forecasting.intervals import rolling_forecast

    t0 = time.perf_counter()
    OUT.mkdir(exist_ok=True)
    df, events, X = load_inputs()
    costs = load_costs()

    # --- 1. Approche actuarielle sur l'historique ------------------------------------------------
    hist = select(df, "train", "validation")
    table, fits = lda_table(hist, observed_losses(hist, costs), costs, select(df, "train"))
    table.to_csv(OUT / "risque_frequence_severite.csv")
    print("Approche frequence x severite (janv. 2022 - juin 2024) :\n")
    print(table.to_string(), "\n")

    # --- 2. Monte Carlo prospectif et backtest de la VaR ------------------------------------------
    print("Previsions hors echantillon et Monte Carlo journalier (quelques minutes)...")
    mu = rolling_forecast(df, events, X, START, END)
    model = build_risk_model(df, mu, costs)
    bt = backtest_var(df, mu, model, costs)
    bt.to_csv(OUT / "risque_backtest_var.csv")

    summary = []
    for level in (0.95, 0.99):
        x = int((bt["perte_reelle"] > bt[f"VaR{round(level * 100)}"]).sum())
        summary.append({"mesure": f"VaR {level:.0%}", "jours": len(bt), "depassements": x,
                        "taux observe %": round(100 * x / len(bt), 1), "taux attendu %": round(100 * (1 - level), 1),
                        "p-valeur Kupiec": round(kupiec_test(x, len(bt), level), 3)})
    summary = pd.DataFrame(summary)
    summary.to_csv(OUT / "risque_backtest_resume.csv", index=False)

    _figures(fits, bt, model, mu, df)
    print(f"\nParametres : patience estimee = {model.patience:.0f} s, "
          f"sigma jour = {model.predictive.day_sigma:.3f}, k = {model.predictive.gamma_shape:.1f}")
    eur = lambda v: f"{v:,.0f} EUR".replace(",", " ")
    print(f"Perte journaliere moyenne : prevue {eur(bt['perte_attendue'].mean())}, "
          f"reelle {eur(bt['perte_reelle'].mean())}")
    print("\nBacktest de la VaR journaliere (janv. - juin 2024) :\n")
    print(summary.to_string(index=False))
    print(f"\nTermine en {time.perf_counter() - t0:.0f} s")


def _figures(fits, bt, model, mu, df) -> None:
    fig_dir = OUT / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    # 13 - severite des pics exceptionnels : comparaison des queues de distribution
    name = "6 Pic exceptionnel de demande"
    x = np.sort(fits[name]["evenements"]["severite"].to_numpy())
    survival = 1 - np.arange(1, len(x) + 1) / (len(x) + 1)
    fig, ax = plt.subplots(figsize=(8, 4.8))
    ax.scatter(x, survival, s=8, color="black", label="evenements observes")
    grid = np.logspace(np.log10(x[0]), np.log10(x[-1] * 2), 300)
    for _, row in fits[name]["severite"].iterrows():
        ax.plot(grid, SEVERITY_LAWS[row["loi"]].sf(grid, *row["params"]), lw=2, label=row["loi"])
    ax.set(xscale="log", yscale="log", ylim=(0.5 / len(x), 1.05), xlabel="cout d'un evenement (EUR)",
           ylabel="probabilite de depasser ce cout",
           title="Pics exceptionnels de demande : la queue de distribution")
    ax.legend()
    fig.tight_layout()
    fig.savefig(fig_dir / "13_severite_pics.png", dpi=150)
    plt.close(fig)

    # 14 - backtest de la VaR
    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.plot(bt.index, bt["perte_reelle"], color="black", lw=1, label="perte reelle du jour")
    ax.plot(bt.index, bt["VaR95"], color="C1", lw=1.2, label="VaR 95 % (prevue la veille)")
    ax.plot(bt.index, bt["VaR99"], color="C3", lw=1.2, ls="--", label="VaR 99 %")
    exc = bt[bt["perte_reelle"] > bt["VaR95"]]
    ax.scatter(exc.index, exc["perte_reelle"], color="red", zorder=3, s=30, label="depassement de la VaR 95 %")
    ax.set(yscale="log", ylabel="EUR / jour", title="Backtest de la VaR journaliere sur la validation")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(fig_dir / "14_backtest_var.png", dpi=150)
    plt.close(fig)

    # 15 - distribution des pertes d'une journee
    day = pd.Timestamp("2024-03-11")
    sl = slice(day, day + pd.Timedelta(hours=23.5))
    r = model.day_risk(mu.loc[sl], aht_forecast(df).loc[sl], df.loc[sl, "agents_scheduled"].to_numpy(),
                       n=5000, seed=1)
    losses = r["pertes_scenarios"]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.hist(losses, bins=80, color="C0", alpha=0.6)
    for value, label, color in ((r["perte_attendue"], "perte attendue", "black"),
                                (r["VaR95"], "VaR 95 %", "C1"), (r["ES95"], "Expected Shortfall 95 %", "C3")):
        ax.axvline(value, color=color, lw=2, label=f"{label} : {value:,.0f} EUR".replace(",", " "))
    ax.set(xlabel="perte operationnelle de la journee (EUR)", ylabel="nombre de scenarios",
           title="5 000 scenarios Monte Carlo du lundi 11 mars 2024 (planning reel)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(fig_dir / "15_distribution_pertes_jour.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    run()