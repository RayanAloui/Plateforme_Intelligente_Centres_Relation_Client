from datetime import date

import pandas as pd
import pytest

from crc.datagen.calendar import build_calendar
from crc.datagen.params import GeneratorParams
from crc.datagen.pipeline import generate


@pytest.fixture(scope="module")
def generated():
    cal = build_calendar(date(2022, 1, 1), date(2024, 12, 31), 30)
    return cal, generate(cal, GeneratorParams(), seed=42, granularity=30)


def _parse(ts_text: pd.Series) -> pd.Series:
    iso = pd.to_datetime(ts_text, format="%Y-%m-%d %H:%M:%S", errors="coerce")
    fr = pd.to_datetime(ts_text, format="%d/%m/%Y %H:%M", errors="coerce")
    return iso.fillna(fr)


def test_row_counts_match_defect_log(generated):
    cal, (_, acd, wfm, _, defects) = generated
    n = len(cal)
    count = defects.groupby(["table", "defect"]).size()
    assert len(acd) == n - count[("acd", "missing_row")] + count[("acd", "duplicate")]
    assert len(wfm) == n - count[("wfm", "missing_row")]


def test_every_timestamp_is_recoverable(generated):
    cal, (_, acd, wfm, _, _) = generated
    for df in (acd, wfm):
        parsed = _parse(df["ts_text"])
        assert parsed.notna().all()
        assert parsed.isin(cal["ts"]).all()


def test_defect_rates_are_small_but_present(generated):
    cal, (_, acd, _, _, defects) = generated
    p = GeneratorParams().defects
    count = defects.groupby("defect").size()
    assert count["outlier"] == pytest.approx(len(cal) * p.outlier_rows, rel=0.1)
    # csat_mean est legitimement vide quand personne n'a repondu a l'enquete
    measured = acd.drop(columns=["ts_text", "source_file", "csat_mean"])
    assert measured.isna().any(axis=1).mean() < 0.02


def test_logged_outliers_exist_in_raw(generated):
    _, (_, acd, _, _, defects) = generated
    raw_ts = set(_parse(acd["ts_text"]))
    outliers = defects.loc[defects["defect"] == "outlier", "ts"]
    assert outliers.isin(raw_ts).all()


def test_ratios_exported_as_percentages(generated):
    _, (_, acd, _, _, _) = generated
    assert acd["service_level_pct"].max() > 1          # exprime en %, pas en ratio
    assert acd["service_level_pct"].max() <= 100


def test_generation_is_reproducible(generated):
    cal, (_, acd, _, _, _) = generated
    _, acd2, _, _, _ = generate(cal, GeneratorParams(), seed=42, granularity=30)
    pd.testing.assert_frame_equal(acd, acd2)