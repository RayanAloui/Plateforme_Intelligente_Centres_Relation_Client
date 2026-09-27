"""Evaluation de la prevision probabiliste (etape 2.6).

    python -m crc.forecasting.intervals

1. Previsions du champion hors echantillon, reentraine chaque mois (juil. 2023 -> juin 2024)
2. Calibration de l'incertitude sur le 2e semestre 2023
3. Verification sur la validation (1er semestre 2024) : les fourchettes a X %
   contiennent-elles vraiment X % des observations ?
"""
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from crc.forecasting.compare import load_inputs
from crc.forecasting.ml import HybridForecaster
from crc.forecasting.probabilistic import CoxPredictive, poisson_quantiles
from crc.forecasting.statistical import daily_level
from crc.splits import SPLITS

START, CALIB_END, END = pd.Timestamp("2023-07-01"), SPLITS["validation"][0], SPLITS["test"][0]
LEVELS = [0.2, 0.4, 0.5, 0.6, 0.8, 0.9, 0.95, 0.98]
OUT = Path("outputs")


def rolling_forecast(df, events, X, start, end) -> pd.Series:
    """Champion reentraine au debut de chaque mois, prevision du mois : toujours hors echantillon."""
    parts = []
    months = pd.date_range(start, end, freq="MS")
    for m0, m1 in zip(months[:-1], months[1:]):
        level = daily_level(df, events, m0)
        p = HybridForecaster().fit(df, X, events, m0, level).predict(X)
        parts.append(p[(p.index >= m0) & (p.index < m1)])
    return pd.concat(parts)


def bounds(level: float) -> tuple[float, float]:
    """Quantiles encadrant une fourchette centrale : 80 % -> (0.10, 0.90)."""
    return round(0.5 - level / 2, 3), round(0.5 + level / 2, 3)


def coverage(y: pd.Series, q: pd.DataFrame, level: float) -> float:
    lo, hi = bounds(level)
    return float(((y >= q[lo]) & (y <= q[hi])).mean())


def run() -> pd.DataFrame:
    t0 = time.perf_counter()
    df, events, X = load_inputs()
    mu = rolling_forecast(df, events, X, START, END)
    y = df.loc[mu.index, "offered"].astype(float)
    dates = pd.Series(df.loc[mu.index, "date"].to_numpy(), index=mu.index)
    ok = ~df.loc[mu.index, "is_imputed"].to_numpy()
    calib = ok & (mu.index < CALIB_END)
    val = ok & (mu.index >= CALIB_END)

    model = CoxPredictive.calibrate(mu[calib], y[calib], dates[calib])
    probs = sorted({p for l in LEVELS for p in bounds(l)} | {0.5})
    q_cox = model.quantiles(mu[val], dates[val], probs)
    q_poi = poisson_quantiles(mu[val], probs)

    table = pd.DataFrame({
        "niveau nominal %": [100 * l for l in LEVELS],
        "couverture Cox %": [100 * coverage(y[val], q_cox, l) for l in LEVELS],
        "couverture Poisson %": [100 * coverage(y[val], q_poi, l) for l in LEVELS],
        "largeur Cox (% du volume)": [100 * ((q_cox[bounds(l)[1]] - q_cox[bounds(l)[0]]) / mu[val]).mean()
                                      for l in LEVELS],
    }).round(1)

    OUT.mkdir(exist_ok=True)
    table.to_csv(OUT / "intervalles_couverture.csv", index=False)
    pd.Series({"day_sigma": model.day_sigma, "gamma_shape": model.gamma_shape}) \
      .to_csv(OUT / "incertitude_parametres.csv", header=["valeur"])
    _figures(table, mu[val], y[val], q_cox)

    print(f"Parametres d'incertitude (calibres sur juil.-dec. 2023) :")
    print(f"  erreur sur le niveau du jour : sigma = {model.day_sigma:.3f}  (~{100 * model.day_sigma:.0f} %)")
    print(f"  surdispersion intra-jour     : k     = {model.gamma_shape:.1f}\n")
    print(f"Couverture sur la validation (janv.-juin 2024), {time.perf_counter() - t0:.0f} s :\n")
    print(table.to_string(index=False))
    return table


def _figures(table, mu, y, q) -> None:
    fig_dir = OUT / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    w = slice("2024-03-11", "2024-03-17 23:30")
    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.fill_between(q.loc[w].index, q.loc[w, 0.01], q.loc[w, 0.99], color="C0", alpha=0.15,
                    label="fourchette a 98 %")
    ax.fill_between(q.loc[w].index, q.loc[w, 0.1], q.loc[w, 0.9], color="C0", alpha=0.35,
                    label="fourchette a 80 %")
    ax.plot(mu.loc[w].index, mu.loc[w], color="C0", lw=1.5, label="prevision centrale")
    out = (y.loc[w] > q.loc[w, 0.99]) | (y.loc[w] < q.loc[w, 0.01])
    ax.scatter(y.loc[w].index, y.loc[w], s=5, color="black", label="observe")
    ax.scatter(y.loc[w][out].index, y.loc[w][out], s=30, color="red", zorder=3,
               label="hors fourchette a 98 %")
    ax.set(title="Prevision probabiliste a J+1 : semaine du 11 mars 2024", ylabel="appels / 30 min")
    ax.legend(fontsize=8, loc="upper right")
    fig.tight_layout()
    fig.savefig(fig_dir / "10_fourchette_semaine.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6, 5.5))
    ax.plot([0, 100], [0, 100], color="grey", ls="--", label="calibration parfaite")
    ax.plot(table["niveau nominal %"], table["couverture Cox %"], marker="o", lw=2,
            label="modele de Cox (retenu)")
    ax.plot(table["niveau nominal %"], table["couverture Poisson %"], marker="s",
            label="hypothese de Poisson")
    ax.set(xlabel="couverture annoncee (%)", ylabel="couverture observee (%)",
           title="Les fourchettes tiennent-elles leurs promesses ?", xlim=(10, 100), ylim=(10, 100))
    ax.legend()
    fig.tight_layout()
    fig.savefig(fig_dir / "11_calibration.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    run()