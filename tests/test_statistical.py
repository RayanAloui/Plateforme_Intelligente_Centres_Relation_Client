import numpy as np
import pandas as pd

from crc.forecasting.features import build_features
from crc.forecasting.metrics import evaluate
from crc.forecasting.statistical import intraday_profile, top_down_forecast
from crc.splits import SPLITS, select

TRAIN_END = SPLITS["validation"][0]


def test_profiles_sum_to_one(simulated):
    history, _, _ = simulated
    profile = intraday_profile(history).dropna()
    assert np.allclose(profile.sum(axis=1), 1.0)


def test_no_data_leakage(simulated):
    """Tripler les volumes a partir du jour D ne doit pas changer la prevision du jour D."""
    history, events, _ = simulated
    day = pd.Timestamp("2024-03-12")
    base = top_down_forecast(history, events, TRAIN_END)
    altered = history.copy()
    altered.loc[altered.index >= day, "offered"] *= 3
    alt = top_down_forecast(altered, events, TRAIN_END)
    same_day = (base.index >= day) & (base.index < day + pd.Timedelta(days=1))
    assert np.allclose(base[same_day], alt[same_day])


def test_beats_best_baseline(simulated):
    history, events, _ = simulated
    val = select(history, "validation")
    val = val[~val["is_imputed"]]
    pred = top_down_forecast(history, events, TRAIN_END).reindex(val.index)
    best_baseline = evaluate(val["offered"], build_features(history, events)["mean_4w"]
                             .reindex(val.index))["WAPE_%"]
    assert evaluate(val["offered"], pred)["WAPE_%"] < best_baseline