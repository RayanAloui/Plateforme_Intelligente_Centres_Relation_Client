from datetime import date

import pandas as pd
import pytest

from crc.datagen.calendar import build_calendar
from crc.datagen.params import GeneratorParams
from crc.datagen.pipeline import generate
from crc.etl.clean import clean, parse_timestamps


@pytest.fixture(scope="module")
def cleaned():
    cal = build_calendar(date(2022, 1, 1), date(2024, 12, 31), 30)
    _, acd, wfm, truth, defects = generate(cal, GeneratorParams(), seed=42, granularity=30)
    core, report = clean(acd, wfm, pd.DatetimeIndex(cal["ts"]))
    return cal, core, report, truth, defects


def test_parse_both_formats():
    s = pd.Series(["2023-01-16 10:00:00", "16/01/2023 10:00", "n'importe quoi"])
    parsed = parse_timestamps(s)
    assert parsed[0] == parsed[1] == pd.Timestamp("2023-01-16 10:00")
    assert pd.isna(parsed[2])


def test_one_complete_row_per_interval(cleaned):
    cal, core, _, _, _ = cleaned
    assert len(core) == len(cal) and core["ts"].is_unique
    assert core.drop(columns=["csat_mean", "imputed_columns"]).notna().all().all()


def test_database_constraints_hold(cleaned):
    _, core, _, _, _ = cleaned
    assert (core["answered"] + core["abandoned"] == core["offered"]).all()
    assert (core["agents_scheduled"] >= core["agents_present"]).all()
    assert (core["avg_handle_seconds"] > 0).all()
    assert core[["service_level", "abandon_rate", "occupancy"]].stack().between(0, 1).all()


def test_all_duplicates_removed(cleaned):
    _, _, report, _, defects = cleaned
    assert report["acd_duplicates_removed"] == (defects["defect"] == "duplicate").sum()


def test_volume_outliers_restored_exactly(cleaned):
    _, core, _, truth, defects = cleaned
    ts = defects.loc[defects["detail"] == "offered_x10", "ts"]
    got = core.set_index("ts").loc[ts, "offered"]
    assert (got == truth.set_index("ts").loc[ts, "offered"]).all()


def test_genuine_incident_peaks_are_kept(cleaned):
    """Le nettoyage ne doit jamais effacer les vrais pics : ce sont eux que la Phase 3 etudie."""
    _, core, _, truth, _ = cleaned
    inc = truth.set_index("ts")["is_incident"]
    c = core.set_index("ts")
    untouched = inc & ~c["is_imputed"]
    assert (c.loc[untouched, "offered"] == truth.set_index("ts").loc[untouched, "offered"]).all()


def test_every_missing_interval_is_flagged(cleaned):
    _, core, _, _, defects = cleaned
    ts = defects.loc[defects["defect"] == "missing_row", "ts"]
    assert core.set_index("ts").loc[ts, "is_imputed"].all()