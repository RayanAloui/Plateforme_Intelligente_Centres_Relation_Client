import pandas as pd

from crc.splits import SPLITS, select, split_of


def test_periods_are_contiguous_and_ordered():
    bounds = list(SPLITS.values())
    for (_, end), (start, _) in zip(bounds, bounds[1:]):
        assert end == start                      # ni trou ni chevauchement


def test_every_interval_has_exactly_one_period():
    ts = pd.date_range("2022-01-01", "2024-12-31 23:30", freq="30min")
    s = split_of(ts)
    assert s.notna().all()
    assert s.value_counts().to_dict() == {"train": 35040, "test": 8832, "validation": 8736}


def test_split_boundary():
    s = split_of(pd.DatetimeIndex(["2023-12-31 23:30", "2024-01-01 00:00"]))
    assert list(s) == ["train", "validation"]


def test_select_keeps_only_requested_periods():
    df = pd.DataFrame({"x": 1}, index=pd.date_range("2023-12-31", periods=96, freq="30min"))
    assert len(select(df, "train")) == 48
    assert len(select(df, "train", "validation")) == 96