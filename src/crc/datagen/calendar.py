"""Construction et chargement de la table de reference ref.calendar."""
from datetime import date, timedelta

import holidays
import pandas as pd

# Vacances scolaires - zone C (academie de Toulouse).
# 2022-2026 : dates officielles. Au-dela : regle approchee (voir approximate_school_holidays).
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
    ("2025-02-15", "2025-03-03"), ("2025-04-12", "2025-04-28"),
    ("2025-07-05", "2025-09-01"), ("2025-10-18", "2025-11-03"),
    ("2025-12-20", "2026-01-05"),
    ("2026-02-21", "2026-03-09"), ("2026-04-18", "2026-05-04"),
    ("2026-07-04", "2026-09-01"), ("2026-10-17", "2026-11-02"),
    ("2026-12-19", "2027-01-04"),
]
KNOWN_UNTIL_YEAR = 2026

DAY_NAMES = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
SEASONS = {12: "Hiver", 1: "Hiver", 2: "Hiver", 3: "Printemps", 4: "Printemps",
           5: "Printemps", 6: "Ete", 7: "Ete", 8: "Ete", 9: "Automne",
           10: "Automne", 11: "Automne"}


def _saturday_near(d: date) -> date:
    """Samedi le plus proche d'une date."""
    return d + timedelta(days=(5 - d.weekday() + 3) % 7 - 3)


def approximate_school_holidays(year: int) -> list[tuple[str, str]]:
    """Dates indicatives pour les annees non encore publiees : memes periodes que d'habitude."""
    periods = [
        (_saturday_near(date(year, 2, 18)), 16),        # hiver
        (_saturday_near(date(year, 4, 15)), 16),        # printemps
        (_saturday_near(date(year, 7, 5)), None),       # ete, jusqu'au 1er septembre
        (_saturday_near(date(year, 10, 19)), 16),       # Toussaint
        (_saturday_near(date(year, 12, 20)), 16),       # Noel
    ]
    out = []
    for start, days in periods:
        end = date(year, 9, 1) if days is None else start + timedelta(days=days)
        out.append((start.isoformat(), end.isoformat()))
    return out


def school_holiday_periods(first_year: int, last_year: int) -> list[tuple[str, str]]:
    periods = list(SCHOOL_HOLIDAYS)
    for year in range(max(first_year, KNOWN_UNTIL_YEAR + 1), last_year + 1):
        periods += approximate_school_holidays(year)
    return periods


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
    for h_start, h_end in school_holiday_periods(start.year - 1, end.year):
        school |= df["ts"].between(pd.Timestamp(h_start), pd.Timestamp(h_end) + timedelta(days=1))
    df["is_school_holiday"] = school

    df["season"] = df["month"].map(SEASONS)
    return df


def load_calendar() -> int:
    from crc.config import get_settings
    from crc.db import execute, get_engine

    s = get_settings()
    df = build_calendar(s.history_start_date, s.history_end_date, s.time_granularity_minutes)
    execute("TRUNCATE ref.calendar CASCADE")
    df.to_sql("calendar", get_engine(), schema="ref", if_exists="append", index=False)
    return len(df)


if __name__ == "__main__":
    n = load_calendar()
    print(f"ref.calendar : {n} intervalles charges.")
