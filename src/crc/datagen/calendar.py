"""Construction et chargement de la table de reference ref.calendar."""
from datetime import date, timedelta

import holidays
import pandas as pd

from crc.config import get_settings
from crc.db import execute, get_engine

# Vacances scolaires - zone C (academie de Toulouse), approximation documentee.
SCHOOL_HOLIDAYS: list[tuple[str, str]] = [
    ("2022-02-19", "2022-03-07"), ("2022-04-23", "2022-05-09"),
    ("2022-07-07", "2022-09-01"), ("2022-10-22", "2022-11-07"),
    ("2022-12-17", "2023-01-03"),
    ("2023-02-18", "2023-03-06"), ("2023-04-22", "2023-05-09"),
    ("2023-07-08", "2023-09-04"), ("2023-10-21", "2023-11-06"),
    ("2023-12-23", "2024-01-08"),
    ("2024-02-17", "2024-03-04"), ("2024-04-06", "2024-04-22"),
    ("2024-07-06", "2024-09-02"), ("2024-10-19", "2024-11-04"),
    ("2024-12-21", "2025-01-06"),
]

DAY_NAMES = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
SEASONS = {12: "Hiver", 1: "Hiver", 2: "Hiver", 3: "Printemps", 4: "Printemps",
           5: "Printemps", 6: "Ete", 7: "Ete", 8: "Ete", 9: "Automne",
           10: "Automne", 11: "Automne"}


def build_calendar(start: date, end: date, granularity_minutes: int) -> pd.DataFrame:
    """Grille temporelle continue en heure locale naive."""
    last = pd.Timestamp(end) + timedelta(days=1) - timedelta(minutes=granularity_minutes)
    ts = pd.date_range(pd.Timestamp(start), last, freq=f"{granularity_minutes}min")
    df = pd.DataFrame({"ts": ts})

    df["date"] = df["ts"].dt.date
    df["year"] = df["ts"].dt.year
    df["month"] = df["ts"].dt.month
    df["week_iso"] = df["ts"].dt.isocalendar().week.astype(int)
    df["day_of_week"] = df["ts"].dt.dayofweek
    df["day_name"] = df["day_of_week"].map(lambda d: DAY_NAMES[d])
    df["hour"] = df["ts"].dt.hour
    df["minute"] = df["ts"].dt.minute
    df["period_index"] = (df["hour"] * 60 + df["minute"]) // granularity_minutes
    df["is_weekend"] = df["day_of_week"] >= 5

    fr = holidays.France(years=range(start.year, end.year + 1))
    df["holiday_name"] = df["date"].map(lambda d: fr.get(d))
    df["is_holiday"] = df["holiday_name"].notna()

    school = pd.Series(False, index=df.index)
    for h_start, h_end in SCHOOL_HOLIDAYS:
        school |= df["ts"].between(pd.Timestamp(h_start), pd.Timestamp(h_end) + timedelta(days=1))
    df["is_school_holiday"] = school

    df["season"] = df["month"].map(SEASONS)
    return df


def load_calendar() -> int:
    s = get_settings()
    df = build_calendar(s.history_start_date, s.history_end_date, s.time_granularity_minutes)
    execute("TRUNCATE ref.calendar CASCADE")
    df.to_sql("calendar", get_engine(), schema="ref", if_exists="append", index=False)
    return len(df)


if __name__ == "__main__":
    n = load_calendar()
    print(f"ref.calendar : {n} intervalles charges.")