from crc.config import get_settings
from crc.db import check_connection


def test_settings_loaded():
    s = get_settings()
    assert s.postgres_db
    assert s.time_granularity_minutes in (15, 30, 60)
    assert s.history_start_date < s.history_end_date


def test_periods_per_day():
    assert get_settings().periods_per_day == 48


def test_database_reachable():
    assert check_connection(), "PostgreSQL injoignable : docker compose up -d ?"