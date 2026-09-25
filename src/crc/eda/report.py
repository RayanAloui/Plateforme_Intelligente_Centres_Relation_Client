"""Analyse exploratoire : figures du memoire et chiffres cles, en une commande.

    python -m crc.eda.report

Chaque figure repond a une question precise et prepare une phase ulterieure.
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")                       # generation de fichiers, sans fenetre
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from crc.datasets import load_history

OUT = Path("outputs/figures")
DAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
MONTHS = ["Jan", "Fev", "Mar", "Avr", "Mai", "Juin", "Juil", "Aout", "Sep", "Oct", "Nov", "Dec"]

plt.rcParams.update({"figure.dpi": 110, "savefig.dpi": 150, "axes.grid": True,
                     "grid.alpha": 0.3, "axes.spines.top": False, "axes.spines.right": False})


def _save(fig, name: str) -> None:
    fig.tight_layout()
    fig.savefig(OUT / f"{name}.png", bbox_inches="tight")
    plt.close(fig)


def fig_tendance(df):
    """L'activite augmente-t-elle au fil des mois ?"""
    daily = df["offered"].resample("D").sum()
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(daily.index, daily, lw=0.6, alpha=0.6, label="volume journalier")
    ax.plot(daily.rolling(28, center=True).mean(), lw=2, label="moyenne mobile 28 jours")
    ax.set(title="Tendance et saisonnalite annuelle", ylabel="appels / jour")
    ax.legend()
    _save(fig, "01_tendance")


def fig_profil_intrajournalier(df):
    """A quelles heures y a-t-il le plus de demandes ?"""
    prof = df.assign(h=df["hour"] + df["minute"] / 60) \
             .pivot_table(index="h", columns="day_of_week", values="offered")
    fig, ax = plt.subplots(figsize=(11, 4.5))
    for d in range(7):
        ax.plot(prof.index, prof[d], lw=2 if d < 5 else 2.5, ls="-" if d < 5 else "--", label=DAYS[d])
    ax.set(title="Profil intra-journalier moyen", xlabel="heure", ylabel="appels / 30 min",
           xticks=range(0, 25, 2))
    ax.legend(ncol=4)
    _save(fig, "02_profil_intrajournalier")


def fig_saisonnalite(df):
    """Le lundi est-il different du vendredi ? Quels mois sont charges ?"""
    daily = df.groupby("date").agg(offered=("offered", "sum"), dow=("day_of_week", "first"),
                                   month=("month", "first"), year=("year", "first"),
                                   holiday=("is_holiday", "first"))
    daily = daily[~daily["holiday"]]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.5))
    a1.boxplot([daily.loc[daily["dow"] == d, "offered"] for d in range(7)], showfliers=False)
    a1.set_xticks(range(1, 8), [d[:3] for d in DAYS])
    a1.set(title="Volume journalier par jour de semaine", ylabel="appels / jour")
    for y, g in daily.groupby("year"):
        a2.plot(range(1, 13), g.groupby("month")["offered"].mean(), marker="o", label=str(y))
    a2.set_xticks(range(1, 13), MONTHS)
    a2.set(title="Volume journalier moyen par mois")
    a2.legend()
    _save(fig, "03_saisonnalite")


def fig_autocorrelation(df, max_lag=2 * 336):
    """Quelle memoire a la serie ? (prepare le choix des variables de la Phase 2)"""
    x = df["offered"].to_numpy(float)
    x = (x - x.mean()) / x.std()
    acf = np.array([1.0] + [np.mean(x[:-k] * x[k:]) for k in range(1, max_lag + 1)])
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.vlines(range(len(acf)), 0, acf, lw=0.6)
    for lag, lab in ((48, "1 jour"), (336, "1 semaine"), (672, "2 semaines")):
        ax.axvline(lag, color="C1", ls="--", lw=1)
        ax.text(lag, 1.02, lab, ha="center", color="C1")
    ax.set(title="Autocorrelation du volume (pas de 30 min)", xlabel="decalage (intervalles)",
           ylabel="autocorrelation", ylim=(min(acf.min() - 0.05, -0.1), 1.1))
    _save(fig, "04_autocorrelation")
    return {48: acf[48], 336: acf[336]}


def fig_charge_vs_service(df):
    """Comment le service se degrade-t-il quand la charge approche la capacite ?"""
    d = df[(df["offered"] >= 20) & ~df["is_imputed"]]
    load = d["offered"] * d["avg_handle_seconds"] / (1800 * d["agents_present"])
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.5))
    hb = a1.hexbin(load, d["service_level"], gridsize=45, bins="log", cmap="viridis",
                   extent=(0, 1.6, 0, 1))
    a1.axvline(1, color="red", ls="--", lw=1)
    a1.set(title="Service level selon la charge par agent",
           xlabel="charge / capacite (offered x AHT / agents presents)", ylabel="service level")
    fig.colorbar(hb, ax=a1, label="nb d'intervalles (log)")
    bins = pd.cut(load, np.arange(0, 1.65, 0.1))
    ab = d.groupby(bins, observed=True)["abandon_rate"].mean()
    a2.bar([b.mid for b in ab.index], ab * 100, width=0.08)
    a2.axvline(1, color="red", ls="--", lw=1)
    a2.set(title="Taux d'abandon moyen selon la charge", xlabel="charge / capacite",
           ylabel="abandon (%)")
    _save(fig, "05_charge_vs_service")


def fig_correlations(df):
    """Quelles variables evoluent ensemble ?"""
    cols = {"offered": "volume", "avg_wait_seconds": "attente", "abandon_rate": "abandon",
            "service_level": "service level", "agents_present": "agents", "avg_handle_seconds": "AHT",
            "occupancy": "occupation", "csat_mean": "satisfaction"}
    c = df[list(cols)].rename(columns=cols).corr(method="spearman")
    fig, ax = plt.subplots(figsize=(7.5, 6.5))
    im = ax.imshow(c, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(c)), c.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(c)), c.columns)
    for i in range(len(c)):
        for j in range(len(c)):
            ax.text(j, i, f"{c.iloc[i, j]:.2f}", ha="center", va="center", fontsize=8)
    ax.grid(False)
    ax.set_title("Correlations de rang (Spearman)")
    fig.colorbar(im, ax=ax, shrink=0.8)
    _save(fig, "06_correlations")
    return c


def fig_dispersion(df):
    """Les volumes sont-ils plus variables qu'un processus de Poisson ? (prepare la Phase 3)"""
    d = df[~df["is_imputed"] & ~df["is_holiday"]]
    # Cellules homogenes : meme jour de semaine, meme demi-heure, meme mois
    g = d.groupby(["year", "month", "day_of_week", "period_index"])["offered"].agg(["mean", "var"])
    g = g[g["mean"] > 5]
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    ax.scatter(g["mean"], g["var"], s=4, alpha=0.3, label="cellules jour x demi-heure x mois")
    m = np.linspace(g["mean"].min(), g["mean"].max(), 100)
    ax.plot(m, m, color="red", lw=2, label="Poisson : variance = moyenne")
    ax.set(xscale="log", yscale="log", xlabel="moyenne", ylabel="variance",
           title="Surdispersion des volumes")
    ax.legend()
    _save(fig, "07_dispersion")
    return float((g["var"] / g["mean"]).median())


def key_figures(df, acf, dispersion) -> pd.DataFrame:
    yearly = df["offered"].resample("YE").sum()
    daily = df["offered"].resample("D").sum()
    wd = df.groupby("day_of_week")["offered"].mean()
    peak = df[~df["is_weekend"]].groupby(["hour", "minute"])["offered"].mean().idxmax()
    w = df["offered"]
    rows = [
        ("Volume annuel", " / ".join(f"{v / 1e6:.2f} M" for v in yearly)),
        ("Croissance annuelle moyenne", f"{(yearly.iloc[-1] / yearly.iloc[0]) ** 0.5 - 1:.1%}"),
        ("Volume journalier moyen", f"{daily.mean():,.0f} appels".replace(",", " ")),
        ("Pic moyen (semaine)", f"{peak[0]:02d}h{peak[1]:02d}"),
        ("Ratio lundi / dimanche", f"{wd[0] / wd[6]:.2f}"),
        ("Service level (pondere volume)", f"{(df['service_level'] * w).sum() / w.sum():.1%}"),
        ("Taux d'abandon global", f"{df['abandoned'].sum() / w.sum():.1%}"),
        ("Intervalles sous 80 % de SL", f"{(df['service_level'] < 0.8).mean():.1%}"),
        ("Autocorrelation a 1 jour / 1 semaine", f"{acf[48]:.2f} / {acf[336]:.2f}"),
        ("Rapport variance / moyenne (median)", f"{dispersion:.1f}  (Poisson = 1)"),
        ("Intervalles reconstitues", f"{df['is_imputed'].mean():.2%}"),
    ]
    return pd.DataFrame(rows, columns=["indicateur", "valeur"])


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = load_history()
    fig_tendance(df)
    fig_profil_intrajournalier(df)
    fig_saisonnalite(df)
    acf = fig_autocorrelation(df)
    fig_charge_vs_service(df)
    fig_correlations(df)
    dispersion = fig_dispersion(df)

    kf = key_figures(df, acf, dispersion)
    kf.to_csv(OUT.parent / "chiffres_cles.csv", index=False)
    print(kf.to_string(index=False))
    print(f"\n7 figures enregistrees dans {OUT}")


if __name__ == "__main__":
    run()