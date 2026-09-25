"""Mesure de la qualite du nettoyage, grace a la verite terrain du generateur.

Impossible avec des donnees reelles : c'est un apport direct du choix d'un
generateur synthetique.
"""
import numpy as np
import pandas as pd

RENAMED = {"service_level_pct": "service_level", "occupancy_pct": "occupancy"}


def _wape(got: pd.Series, true: pd.Series) -> float:
    """Erreur absolue ponderee : sum|ecart| / sum(vrai), robuste aux petits volumes."""
    return float((got - true).abs().sum() / true.abs().sum())


def quality_report(core, truth, defects, report) -> pd.DataFrame:
    c, t = core.set_index("ts"), truth.set_index("ts")
    rows = []

    def add(table, kind, n, indicator, value, reference=np.nan):
        rows.append({"table": table, "defaut": kind, "injectes": n, "indicateur": indicator,
                     "valeur_%": round(100 * value, 1), "reference_%": round(100 * reference, 1)})

    for (table, kind), g in defects.groupby(["table", "defect"]):
        ts = pd.Index(g["ts"]).unique()
        if kind == "alt_timestamp_format":
            add(table, kind, len(g), "dates relues", 1 - report[f"{table}_unparseable"] / len(g))
        elif kind == "duplicate":
            add(table, kind, len(g), "doublons supprimes",
                report[f"{table}_duplicates_removed"] / len(g))
        elif kind == "outlier":
            vol = g.loc[g["detail"] == "offered_x10", "ts"]
            aht = g.loc[g["detail"] != "offered_x10", "ts"]
            ok = pd.concat([
                (c.loc[vol, "offered"] - t.loc[vol, "offered"]).abs() <= 0.5,
                (c.loc[aht, "avg_handle_seconds"] / t.loc[aht, "avg_handle_seconds"] - 1).abs() <= 0.25,
            ])
            add(table, kind, len(g), "valeurs corrigees", ok.mean())
        elif kind == "missing_cell":
            g = g[g["detail"] != "csat_mean"]          # absence legitime, non reconstituee
            exact = [
                (c.loc[r.ts, RENAMED.get(r.detail, r.detail)]
                 - t.loc[r.ts, RENAMED.get(r.detail, r.detail)]) ** 2 < 1e-6
                for r in g.itertuples()
            ]
            add(table, kind, len(g), "cellules reconstituees a l'identique", np.mean(exact))
        elif kind == "missing_row" and table == "acd":
            # Reference : erreur d'un oracle qui connaitrait l'intensite reelle.
            # Aucune methode d'imputation ne peut descendre sous ce plancher.
            add(table, kind, len(g), "erreur d'imputation du volume (WAPE)",
                _wape(c.loc[ts, "offered"], t.loc[ts, "offered"]),
                _wape(t.loc[ts, "lambda_true"], t.loc[ts, "offered"]))
        elif kind == "missing_row" and table == "wfm":
            add(table, kind, len(g), "erreur d'imputation des agents presents (WAPE)",
                _wape(c.loc[ts, "agents_present"], t.loc[ts, "agents_present"]))
    return pd.DataFrame(rows)