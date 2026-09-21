import pytest

from crc.config import get_settings
from crc.db import read_sql

EXPECTED_TABLES = {
    ("ref", "calendar"), ("ref", "events"), ("ref", "cost_parameters"),
    ("raw", "acd_export"), ("raw", "wfm_roster"), ("raw", "csat_survey"),
    ("core", "interval_metrics"), ("core", "etl_runs"),
    ("features", "feature_catalog"),
}


def test_all_tables_exist():
    df = read_sql("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema IN ('ref','raw','core','features')
    """)
    found = set(map(tuple, df.values))
    assert EXPECTED_TABLES <= found, f"Manquant : {EXPECTED_TABLES - found}"


def test_calendar_is_complete():
    s = get_settings()
    n = read_sql("SELECT COUNT(*) AS n FROM ref.calendar")["n"].iloc[0]
    days = (s.history_end_date - s.history_start_date).days + 1
    assert n == days * s.periods_per_day


def test_calendar_has_no_gap():
    df = read_sql("SELECT ts FROM ref.calendar ORDER BY ts")
    deltas = df["ts"].diff().dropna().unique()
    assert len(deltas) == 1, "La grille temporelle comporte des trous"


def test_cost_parameters_seeded():
    df = read_sql("SELECT param_name FROM ref.cost_parameters")
    assert {"cost_agent_hour", "sla_target_seconds"} <= set(df["param_name"])


def test_flow_balance_constraint_is_enforced():
    from sqlalchemy.exc import IntegrityError
    from crc.db import execute
    with pytest.raises(IntegrityError):
        execute("""
            INSERT INTO core.interval_metrics
              (ts, offered, answered, abandoned, avg_wait_seconds, avg_handle_seconds,
               agents_scheduled, agents_present, agents_absent,
               service_level, abandon_rate, occupancy)
            VALUES ('2022-01-03 09:00:00', 10, 9, 5, 12.0, 240.0, 5, 5, 0, 0.9, 0.5, 0.8)
        """)