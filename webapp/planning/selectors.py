"""Lecture des donnees pour les pages : journees disponibles, previsions, realise."""
from datetime import date, timedelta

import pandas as pd
from django.db import connection

from planning.models import DailyForecast, PlatformState


def platform_today() -> date | None:
    return PlatformState.get().current_date


def forecast_days() -> list[date]:
    return list(DailyForecast.objects.order_by("date").values_list("date", flat=True))


def resolve_day(request) -> date | None:
    """Journee affichee : ?jour=AAAA-MM-JJ si elle existe, sinon le lendemain planifie."""
    days = forecast_days()
    if not days:
        return None
    wanted = request.GET.get("jour")
    if wanted:
        try:
            d = date.fromisoformat(wanted)
            if d in days:
                return d
        except ValueError:
            pass
    return days[-1]


def day_navigation(day: date) -> dict:
    days = forecast_days()
    i = days.index(day)
    today = platform_today()
    return {"day": day, "previous": days[i - 1] if i > 0 else None,
            "next": days[i + 1] if i < len(days) - 1 else None,
            "is_future": today is not None and day > today,
            "is_tomorrow": today is not None and day == today + timedelta(days=1),
            "first": days[0], "last": days[-1]}


def forecast_frame(forecast: DailyForecast) -> pd.DataFrame:
    rows = forecast.intervals.values("ts", "expected", "q01", "q10", "q50", "q90", "q99", "aht_expected")
    return pd.DataFrame(list(rows)).set_index("ts")


def realized(day: date) -> pd.DataFrame | None:
    """Journee reellement observee (core), si elle est deja integree."""
    with connection.cursor() as cur:
        cur.execute("""SELECT ts, offered, abandoned, avg_wait_seconds, service_level, agents_present,
                              agents_scheduled, avg_handle_seconds
                       FROM core.interval_metrics WHERE ts >= %s AND ts < %s ORDER BY ts""",
                    [day, day + timedelta(days=1)])
        rows = cur.fetchall()
    if not rows:
        return None
    cols = ["ts", "offered", "abandoned", "avg_wait_seconds", "service_level", "agents_present",
            "agents_scheduled", "avg_handle_seconds"]
    df = pd.DataFrame(rows, columns=cols).set_index("ts")
    return df.astype({c: float for c in cols[1:]})
