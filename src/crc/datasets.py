"""Chargement des donnees propres, jointes au calendrier. Point d'entree commun aux phases 1 a 4."""
import pandas as pd

from crc.db import read_sql


def load_history(include_imputed: bool = True) -> pd.DataFrame:
    """Historique core + attributs calendaires, indexe par horodatage."""
    df = read_sql("""
        SELECT m.*, c.date, c.year, c.month, c.week_iso, c.day_of_week, c.day_name,
               c.hour, c.minute, c.period_index, c.is_weekend, c.is_holiday,
               c.is_school_holiday, c.season
        FROM core.interval_metrics m
        JOIN ref.calendar c USING (ts)
        ORDER BY ts
    """)
    if not include_imputed:
        df = df[~df["is_imputed"]]
    return df.set_index("ts")