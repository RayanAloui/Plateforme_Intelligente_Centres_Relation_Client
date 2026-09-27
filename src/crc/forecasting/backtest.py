"""Evaluation glissante mois par mois (rolling origin).

    python -m crc.forecasting.backtest

Pour chaque mois M de juillet 2023 a juin 2024 : on reentraine les modeles sur
tout ce qui precede M, puis on prevoit M. On couvre ainsi les 12 mois de l'annee,
alors que la validation seule ne couvre que janvier-juin. La periode de test
(juillet-decembre 2024) n'est jamais touchee.
"""
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from crc.forecasting.compare import TRUTH, load_inputs
from crc.forecasting.metrics import evaluate
from crc.forecasting.ml import HybridForecaster, lightgbm_direct
from crc.forecasting.statistical import daily_level, top_down_forecast
from crc.splits import SPLITS

FIRST_FOLD = pd.Timestamp("2023-07-01")
OUT = Path("outputs")
MODELS = ["Hybride SARIMAX + LightGBM", "SARIMAX journalier + profil", "LightGBM direct",
          "Moyenne 4 semaines", "Naif semaine"]


def folds() -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    starts = pd.date_range(FIRST_FOLD, SPLITS["test"][0], freq="MS")
    return list(zip(starts[:-1], starts[1:]))


def forecast_fold(df, events, X, start) -> dict[str, pd.Series]:
    """Tous les modeles, entraines sur les donnees anterieures a `start`."""
    level = daily_level(df, events, start)                      # un seul SARIMAX par pli
    return {
        "Hybride SARIMAX + LightGBM": HybridForecaster().fit(df, X, events, start, level).predict(X),
        "SARIMAX journalier + profil": top_down_forecast(df, events, start, level),
        "LightGBM direct": lightgbm_direct(df, X, start),
        "Moyenne 4 semaines": X["mean_4w"],
        "Naif semaine": X["lag_1w"],
    }


def run() -> pd.DataFrame:
    t0 = time.perf_counter()
    df, events, X = load_inputs()
    truth = pd.read_parquet(TRUTH).set_index("ts") if TRUTH.exists() else None
    rows, sample = [], None

    for start, end in folds():
        mask = (df.index >= start) & (df.index < end) & ~df["is_imputed"].to_numpy()
        y = df.loc[mask, "offered"]
        preds = forecast_fold(df, events, X, start)
        if truth is not None:
            preds["(Oracle)"] = truth["lambda_true"]
        for name, p in preds.items():
            m = evaluate(y, p.reindex(y.index))
            rows.append({"mois": start.strftime("%Y-%m"), "modele": name,
                         "WAPE_%": m["WAPE_%"], "biais_%": m["biais_%"]})
        if start == pd.Timestamp("2024-03-01"):
            sample = pd.DataFrame({k: preds[k] for k in MODELS[:2]}).assign(observe=df["offered"])
        print(f"  {start:%Y-%m} termine")

    res = pd.DataFrame(rows)
    wape = res.pivot(index="mois", columns="modele", values="WAPE_%")
    summary = pd.DataFrame({
        "WAPE moyenne %": wape.mean(),
        "WAPE pire mois %": wape.max(),
        "mois gagnes": (wape[MODELS].rank(axis=1)[MODELS] == 1).sum().reindex(wape.columns),
        "biais moyen %": res.groupby("modele")["biais_%"].mean(),
    }).round(2).sort_values("WAPE moyenne %")

    OUT.mkdir(exist_ok=True)
    wape.round(2).to_csv(OUT / "backtest_wape_par_mois.csv")
    summary.to_csv(OUT / "backtest_resume.csv")
    _figures(wape, sample)

    print(f"\nEvaluation glissante : {len(folds())} mois, {time.perf_counter() - t0:.0f} s\n")
    print(summary.to_string())
    return summary


def _figures(wape: pd.DataFrame, sample: pd.DataFrame) -> None:
    fig_dir = OUT / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(11, 4.5))
    for name in MODELS:
        ax.plot(wape.index, wape[name], marker="o", lw=2 if name.startswith("Hybride") else 1.2,
                label=name)
    if "(Oracle)" in wape:
        ax.fill_between(wape.index, 0, wape["(Oracle)"], color="grey", alpha=0.2,
                        label="zone inatteignable (hasard irreductible)")
    ax.set(title="Erreur de prevision mois par mois (evaluation glissante)",
           ylabel="WAPE (%)", ylim=(0, None))
    ax.tick_params(axis="x", rotation=45)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(fig_dir / "08_backtest_mensuel.png", dpi=150)
    plt.close(fig)

    week = sample.loc["2024-03-11":"2024-03-17"]
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(week.index, week["observe"], color="black", lw=1, label="observe")
    ax.plot(week.index, week[MODELS[0]], lw=2, label=MODELS[0])
    ax.plot(week.index, week[MODELS[1]], lw=1.2, ls="--", label=MODELS[1])
    ax.set(title="Semaine du 11 mars 2024 : prevision a J+1 et realite", ylabel="appels / 30 min")
    ax.legend()
    fig.tight_layout()
    fig.savefig(fig_dir / "09_exemple_semaine.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    run()