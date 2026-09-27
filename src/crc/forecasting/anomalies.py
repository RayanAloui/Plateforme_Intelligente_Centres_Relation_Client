"""Detection d'anomalies de volume (module 7), a partir de la prevision probabiliste.

Principe : une observation est anormale non pas parce qu'elle est elevee, mais
parce qu'elle est INVRAISEMBLABLE compte tenu de ce qu'on attendait.
300 appels un lundi a 10h est normal ; 300 appels un dimanche a 3h ne l'est pas.

    niveau 1 - anomalie moderee : au-dessus du quantile 99 %   -> surveiller
    niveau 2 - anomalie forte   : au-dessus du quantile 99,9 % -> intervenir

    python -m crc.forecasting.anomalies     (evaluation contre les incidents simules)
"""
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from crc.forecasting.probabilistic import CoxPredictive

LABELS = {0: "normal", 1: "anomalie moderee", 2: "anomalie forte"}
OUT = Path("outputs")


@dataclass
class AnomalyDetector:
    predictive: CoxPredictive
    moderate: float = 0.99
    strong: float = 0.999

    def detect(self, mu: pd.Series, y: pd.Series, dates: pd.Series,
               n: int = 4000, seed: int = 0) -> pd.DataFrame:
        q = self.predictive.quantiles(mu, dates, (self.moderate, self.strong), n=n, seed=seed)
        level = np.where(y > q[self.strong], 2, np.where(y > q[self.moderate], 1, 0))
        return pd.DataFrame({
            "attendu": mu.round(1), "observe": y,
            "seuil_modere": q[self.moderate], "seuil_fort": q[self.strong],
            "ecart_%": (100 * (y / mu - 1)).round(1),
            "niveau": level, "libelle": pd.Series(level, index=mu.index).map(LABELS),
        }, index=mu.index)


def incident_mask(index: pd.DatetimeIndex, incidents: pd.DataFrame) -> np.ndarray:
    t, mask = index.to_numpy(), np.zeros(len(index), dtype=bool)
    for ev in incidents.itertuples():
        mask |= (t >= np.datetime64(ev.start_ts)) & (t < np.datetime64(ev.end_ts))
    return mask


def evaluate_rule(flag: pd.Series, incidents: pd.DataFrame, excess: pd.Series, weeks: float) -> dict:
    """Detection par incident (au moins une alerte pendant l'incident) et fausses alertes."""
    inside = incident_mask(flag.index, incidents)
    detected = []
    for ev in incidents.itertuples():
        during = (flag.index >= ev.start_ts) & (flag.index < ev.end_ts)
        detected.append(bool(flag[during].any()))
    detected = np.array(detected)
    impactful = (excess >= 100).to_numpy()
    return {
        "incidents detectes %": 100 * detected.mean(),
        "incidents a fort impact detectes %": 100 * detected[impactful].mean(),
        "fausses alertes / semaine": (flag & ~inside).sum() / weeks,
        "precision %": 100 * (flag & inside).sum() / max(flag.sum(), 1),
    }


def run() -> pd.DataFrame:
    from crc.forecasting.compare import load_inputs
    from crc.forecasting.intervals import CALIB_END, END, START, rolling_forecast

    df, events, X = load_inputs()
    mu = rolling_forecast(df, events, X, START, END)
    idx = mu.index
    y = df.loc[idx, "offered"].astype(float)
    dates = pd.Series(df.loc[idx, "date"].to_numpy(), index=idx)
    ok = pd.Series(~df.loc[idx, "is_imputed"].to_numpy(), index=idx)

    predictive = CoxPredictive.calibrate(mu[ok & (idx < CALIB_END)], y[ok & (idx < CALIB_END)],
                                         dates[ok & (idx < CALIB_END)])
    result = AnomalyDetector(predictive).detect(mu, y, dates)

    # Verite terrain : les incidents techniques (connus apres coup, jamais par le modele)
    incidents = events[(events["event_type"] == "incident_technique")
                       & (events["start_ts"] >= idx[0]) & (events["start_ts"] < idx[-1])]
    excess = pd.Series([(y - mu)[(idx >= e.start_ts) & (idx < e.end_ts)].sum()
                        for e in incidents.itertuples()], index=incidents.index)
    weeks = len(idx) / 336

    # Methodes concurrentes
    moderate = (result["niveau"] >= 1) & ok
    feats = df[["offered", "period_index", "day_of_week", "is_holiday"]].astype(float)
    train = (df.index < START) & ~df["is_imputed"].to_numpy()
    iso = IsolationForest(n_estimators=300, contamination=moderate.mean(), random_state=0)
    iso_flag = pd.Series(iso.fit(feats[train]).predict(feats.loc[idx]) == -1, index=idx) & ok

    rules = {
        "Seuil fixe (+50 % vs prevision)": (y > 1.5 * mu) & ok,
        "Isolation Forest (sans prevision)": iso_flag,
        "Anomalie moderee (> q99)": moderate,
        "Anomalie forte (> q99,9)": (result["niveau"] == 2) & ok,
    }
    table = pd.DataFrame({k: evaluate_rule(v, incidents, excess, weeks) for k, v in rules.items()}).T.round(1)

    OUT.mkdir(exist_ok=True)
    table.to_csv(OUT / "anomalies_comparaison.csv")
    _figure(result, incidents)
    _print_alert(result)
    print(f"\n{len(incidents)} incidents sur {weeks:.0f} semaines "
          f"(dont {(excess >= 100).sum()} a fort impact, >= 100 appels excedentaires)\n")
    print(table.to_string())
    return table


def _print_alert(result: pd.DataFrame) -> None:
    """Exemple d'alerte au format du document de cadrage (module 7)."""
    r = result.loc[result["observe"].sub(result["seuil_fort"]).idxmax()]
    print("\n+-----------------------------------+")
    print("|        ANOMALIE DETECTEE          |")
    print(f"|  Intervalle   : {r.name:%d/%m/%Y %H:%M}  |")
    print(f"|  Volume prevu : {r['attendu']:>8.0f}          |")
    print(f"|  Volume observe : {r['observe']:>6.0f}          |")
    print(f"|  Ecart        : {r['ecart_%']:>+7.0f} %         |")
    print(f"|  Niveau       : {r['libelle']:<18}|")
    print("+-----------------------------------+")


def _figure(result: pd.DataFrame, incidents: pd.DataFrame) -> None:
    ev = incidents.loc[incidents["intensity"].idxmax()]
    day = result.loc[ev["start_ts"].normalize(): ev["start_ts"].normalize() + pd.Timedelta(hours=23.5)]
    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.axvspan(ev["start_ts"], ev["end_ts"], color="orange", alpha=0.15, label="incident reel")
    ax.plot(day.index, day["attendu"], lw=2, label="prevision")
    ax.plot(day.index, day["seuil_fort"], ls="--", color="grey", label="seuil d'anomalie forte (q99,9)")
    ax.scatter(day.index, day["observe"], s=10, color="black", label="observe")
    for lvl, color in ((1, "orange"), (2, "red")):
        pts = day[day["niveau"] == lvl]
        ax.scatter(pts.index, pts["observe"], s=45, color=color, zorder=3, label=LABELS[lvl])
    ax.set(title=f"Detection de l'incident du {ev['start_ts']:%d/%m/%Y}", ylabel="appels / 30 min")
    ax.legend(fontsize=8)
    fig.tight_layout()
    (OUT / "figures").mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "figures" / "12_detection_incident.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    run()