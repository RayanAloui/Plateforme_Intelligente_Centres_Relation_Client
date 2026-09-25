"""Nettoyage : des exports bruts (raw) a la table propre (core).

Ordre des operations (il compte) :
  1. convertir les horodatages      -> sinon certains doublons restent invisibles
  2. supprimer les doublons
  3. corriger les valeurs impossibles (regles metier, pas de filtre statistique)
  4. recaler sur la grille du calendrier -> les intervalles manquants apparaissent
  5. reconstruire ce qui peut l'etre par identite comptable
  6. interpoler le reste, en tracant chaque valeur reconstituee
"""
import numpy as np
import pandas as pd

TS_FORMATS = ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M")
AHT_VALID_RANGE = (30.0, 3600.0)          # une duree moyenne hors de cet intervalle est impossible

ACD_COLS = ["offered", "answered", "abandoned", "avg_wait_seconds", "avg_handle_seconds",
            "service_level", "occupancy", "csat_mean", "csat_responses"]
WFM_COLS = ["agents_scheduled", "agents_present", "agents_absent"]
COUNT_COLS = ["offered", "answered", "abandoned", "csat_responses"] + WFM_COLS


def parse_timestamps(text: pd.Series) -> pd.Series:
    """Essaie chaque format connu ; NaT si aucun ne convient."""
    out = pd.Series(pd.NaT, index=text.index, dtype="datetime64[ns]")
    for fmt in TS_FORMATS:
        out = out.fillna(pd.to_datetime(text, format=fmt, errors="coerce"))
    return out


def _to_grid(df: pd.DataFrame, grid: pd.DatetimeIndex, report: dict, name: str) -> pd.DataFrame:
    """Horodatages -> doublons -> grille. Renseigne le rapport."""
    df = df.assign(ts=parse_timestamps(df["ts_text"]))
    report[f"{name}_unparseable"] = int(df["ts"].isna().sum())
    df = df.dropna(subset=["ts"])

    n = len(df)
    df = df.drop_duplicates(subset="ts", keep="first")
    report[f"{name}_duplicates_removed"] = n - len(df)

    df = df.set_index("ts").reindex(grid)
    report[f"{name}_missing_intervals"] = int(df.isna().all(axis=1).sum())
    return df


def clean(acd_raw: pd.DataFrame, wfm_raw: pd.DataFrame, grid: pd.DatetimeIndex):
    """Renvoie (table core, rapport de nettoyage)."""
    report: dict = {}

    acd = _to_grid(acd_raw, grid, report, "acd")
    acd["service_level"] = acd["service_level_pct"] / 100
    acd["occupancy"] = acd["occupancy_pct"] / 100
    acd = acd[ACD_COLS].astype(float)
    wfm = _to_grid(wfm_raw, grid, report, "wfm")[WFM_COLS].astype(float)

    df = acd.join(wfm)
    missing = df.isna()        # ce qui manque avant toute correction
    corrected = pd.DataFrame(False, index=df.index, columns=df.columns)

    # --- Valeurs impossibles -------------------------------------------------------------
    bad_aht = ~df["avg_handle_seconds"].between(*AHT_VALID_RANGE) & df["avg_handle_seconds"].notna()
    df.loc[bad_aht, "avg_handle_seconds"] = np.nan
    corrected["avg_handle_seconds"] |= bad_aht

    # Identite de flux : chaque appel offert est soit traite, soit abandonne.
    # Un volume incoherent avec ses composantes est une erreur de saisie, pas un pic :
    # on le recalcule. Les vrais pics (incidents) respectent l'identite et sont conserves.
    flow = df["answered"] + df["abandoned"]
    bad_flow = df["offered"].notna() & flow.notna() & (df["offered"] != flow)
    df.loc[bad_flow, "offered"] = flow[bad_flow]
    corrected["offered"] |= bad_flow
    report["aht_impossible_fixed"] = int(bad_aht.sum())
    report["flow_inconsistencies_fixed"] = int(bad_flow.sum())

    # --- Reconstruction par identite (une seule inconnue sur trois) -----------------------
    o, a, b = df["offered"], df["answered"], df["abandoned"]
    df.loc[o.isna() & a.notna() & b.notna(), "offered"] = a + b
    df.loc[a.isna() & o.notna() & b.notna(), "answered"] = o - b
    df.loc[b.isna() & o.notna() & a.notna(), "abandoned"] = o - a
    s, p = df["agents_scheduled"], df["agents_present"]
    df.loc[df["agents_absent"].isna() & s.notna() & p.notna(), "agents_absent"] = s - p

    # --- Interpolation temporelle du reste -----------------------------------------------
    # csat_mean n'est pas interpolee : une satisfaction absente est une information reelle.
    to_fill = [c for c in df.columns if c != "csat_mean"]
    df[to_fill] = df[to_fill].interpolate(method="time", limit_direction="both")
    df[COUNT_COLS] = df[COUNT_COLS].round()

    # --- Coherence finale -------------------------------------------------------------------
    df["abandoned"] = df[["abandoned", "offered"]].min(axis=1)
    df["answered"] = df["offered"] - df["abandoned"]
    df["agents_present"] = df[["agents_present", "agents_scheduled"]].min(axis=1).clip(lower=1)
    df["agents_absent"] = df["agents_scheduled"] - df["agents_present"]
    df["service_level"] = df["service_level"].clip(0, 1)
    df["occupancy"] = df["occupancy"].clip(0, 1)
    has_calls = df["offered"] > 0
    df["abandon_rate"] = np.where(has_calls, df["abandoned"] / df["offered"].where(has_calls, 1), 0.0)

    # --- Tracabilite ----------------------------------------------------------------------------
    touched = (missing | corrected).drop(columns="csat_mean")
    df["is_imputed"] = touched.any(axis=1)
    cols = touched.columns.to_numpy()
    df["imputed_columns"] = [list(cols[row]) if row.any() else None for row in touched.to_numpy()]
    report["intervals_imputed"] = int(df["is_imputed"].sum())

    df[COUNT_COLS] = df[COUNT_COLS].astype(int)
    df.index.name = "ts"
    return df.reset_index(), report