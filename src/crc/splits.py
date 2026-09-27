"""Decoupage temporel des donnees, fige une fois pour toutes.

    entrainement : 2022-01-01 -> 2023-12-31   (2 ans : chaque saison vue deux fois)
    validation   : 2024-01-01 -> 2024-06-30   (choix des modeles et des reglages)
    test         : 2024-07-01 -> 2024-12-31   (evaluation finale, UNE seule fois)

Regle : aucune decision (modele, parametre, seuil) ne doit etre prise en regardant
la periode de test. Elle sert uniquement au tableau final des trois strategies.
"""
import pandas as pd

SPLITS = {
    "train": (pd.Timestamp("2022-01-01"), pd.Timestamp("2024-01-01")),
    "validation": (pd.Timestamp("2024-01-01"), pd.Timestamp("2024-07-01")),
    "test": (pd.Timestamp("2024-07-01"), pd.Timestamp("2025-01-01")),
}


def split_of(ts: pd.Series | pd.DatetimeIndex) -> pd.Series:
    """Nom de la periode ('train', 'validation', 'test') de chaque horodatage."""
    ts = pd.Series(pd.DatetimeIndex(ts))
    out = pd.Series(pd.NA, index=ts.index, dtype="string")
    for name, (start, end) in SPLITS.items():
        out[(ts >= start) & (ts < end)] = name
    return out


def select(df: pd.DataFrame, *names: str) -> pd.DataFrame:
    """Lignes d'un DataFrame indexe par horodatage appartenant aux periodes demandees."""
    mask = split_of(df.index).isin(names).to_numpy()
    return df[mask]