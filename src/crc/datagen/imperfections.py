"""Passage des donnees propres aux exports bruts, avec des imperfections realistes.

Chaque defaut injecte est journalise : en 1.4, on pourra mesurer quelle part
des defauts le pipeline de nettoyage detecte et corrige.
"""
import numpy as np
import pandas as pd

from crc.datagen.params import DefectParams

ACD_NUMERIC = ["offered", "answered", "abandoned", "avg_wait_seconds",
               "avg_handle_seconds", "service_level_pct", "occupancy_pct",
               "csat_mean", "csat_responses"]


def _source_file(ts: pd.Series, system: str) -> pd.Series:
    """Nom du fichier d'export mensuel, ex. acd_2023_01.csv."""
    return system + "_" + ts.dt.strftime("%Y_%m") + ".csv"


def _pick(rng, n: int, rate: float) -> np.ndarray:
    return rng.choice(n, size=int(round(n * rate)), replace=False)


def to_raw_exports(clean: pd.DataFrame, p: DefectParams, rng: np.random.Generator):
    """Renvoie (acd_export, wfm_roster, journal_des_defauts)."""
    log = []
    ts = pd.to_datetime(clean["ts"])

    # --- Export ACD : les ratios sont exprimes en pourcentage, comme dans les vrais outils
    acd = pd.DataFrame({
        "ts": ts,
        "offered": clean["offered"].astype(float),
        "answered": clean["answered"].astype(float),
        "abandoned": clean["abandoned"].astype(float),
        "avg_wait_seconds": clean["avg_wait_seconds"],
        "avg_handle_seconds": clean["avg_handle_seconds"],
        "service_level_pct": (clean["service_level"] * 100).round(2),
        "occupancy_pct": (clean["occupancy"] * 100).round(2),
        "csat_mean": clean["csat_mean"],
        "csat_responses": clean["csat_responses"].astype(float),
    })
    wfm = pd.DataFrame({
        "ts": ts,
        "agents_scheduled": clean["agents_scheduled"].astype(float),
        "agents_present": clean["agents_present"].astype(float),
        "agents_absent": clean["agents_absent"].astype(float),
    })

    # 1. Intervalles absents (chaque systeme a ses propres trous)
    for name, df, rate in (("acd", acd, p.missing_rows_acd), ("wfm", wfm, p.missing_rows_wfm)):
        drop = _pick(rng, len(df), rate)
        log += [(t, name, "missing_row", "") for t in df.loc[drop, "ts"]]
        df.drop(index=drop, inplace=True)
        df.reset_index(drop=True, inplace=True)

    # 2. Valeurs aberrantes (erreur de saisie ou de capteur)
    for i in _pick(rng, len(acd), p.outlier_rows):
        kind = rng.choice(["offered_x10", "handle_zero", "handle_huge"])
        if kind == "offered_x10":
            acd.loc[i, "offered"] *= 10
        elif kind == "handle_zero":
            acd.loc[i, "avg_handle_seconds"] = 0.0
        else:
            acd.loc[i, "avg_handle_seconds"] = 99999.0
        log.append((acd.loc[i, "ts"], "acd", "outlier", kind))

    # 3. Cellules manquantes
    rows = _pick(rng, len(acd), p.missing_cells)
    for i, col in zip(rows, rng.choice(ACD_NUMERIC, size=len(rows))):
        acd.loc[i, col] = np.nan
        log.append((acd.loc[i, "ts"], "acd", "missing_cell", col))

    # 4. Doublons (meme intervalle exporte deux fois)
    dup = acd.sample(frac=p.duplicate_rows, random_state=rng)
    log += [(t, "acd", "duplicate", "") for t in dup["ts"]]
    acd = pd.concat([acd, dup]).sort_values("ts", kind="stable").reset_index(drop=True)

    # 5. Horodatages en texte, dont une partie dans un autre format
    acd["ts_text"] = acd["ts"].dt.strftime("%Y-%m-%d %H:%M:%S")
    alt = _pick(rng, len(acd), p.alt_timestamp_format)
    acd.loc[alt, "ts_text"] = acd.loc[alt, "ts"].dt.strftime("%d/%m/%Y %H:%M")
    log += [(t, "acd", "alt_timestamp_format", "") for t in acd.loc[alt, "ts"]]
    wfm["ts_text"] = wfm["ts"].dt.strftime("%Y-%m-%d %H:%M:%S")

    acd["source_file"] = _source_file(acd["ts"], "acd")
    wfm["source_file"] = _source_file(wfm["ts"], "wfm")

    defects = pd.DataFrame(log, columns=["ts", "table", "defect", "detail"])
    return (acd.drop(columns="ts"), wfm.drop(columns="ts"),
            defects.sort_values("ts").reset_index(drop=True))