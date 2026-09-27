import numpy as np
import pandas as pd
import pytest

from crc.forecasting.features import build_features
from crc.forecasting.metrics import evaluate
from crc.forecasting.ml import HybridForecaster, lightgbm_direct
from crc.splits import SPLITS, select

TRAIN_END = SPLITS["validation"][0]


@pytest.fixture(scope="module")
def setup(simulated):
    history, events, _ = simulated
    X = build_features(history, events)
    val = select(history, "validation")
    return history, events, X, val[~val["is_imputed"]]


def test_no_data_leakage(setup):
    """Tripler les volumes a partir du jour D ne doit pas changer la prevision du jour D."""
    history, events, X, _ = setup
    day = pd.Timestamp("2024-03-12")
    base = HybridForecaster().fit(history, X, events, TRAIN_END).predict(X)

    altered = history.copy()
    altered.loc[altered.index >= day, "offered"] *= 3
    X_alt = build_features(altered, events)
    alt = HybridForecaster().fit(altered, X_alt, events, TRAIN_END).predict(X_alt)

    same_day = (base.index >= day) & (base.index < day + pd.Timedelta(days=1))
    assert np.allclose(base[same_day], alt[same_day])


def test_hybrid_is_accurate_and_unbiased(setup):
    history, events, X, val = setup
    pred = HybridForecaster().fit(history, X, events, TRAIN_END).predict(X).reindex(val.index)
    m = evaluate(val["offered"], pred)
    best_baseline = evaluate(val["offered"], X["mean_4w"].reindex(val.index))["WAPE_%"]
    assert m["WAPE_%"] < best_baseline
    assert abs(m["biais_%"]) < 2                       # critere du DSO1


def test_direct_lightgbm_underestimates_growth(setup):
    """Constat documente dans le memoire : les arbres n'extrapolent pas la tendance."""
    history, _, X, val = setup
    pred = lightgbm_direct(history, X, TRAIN_END).reindex(val.index)
    assert evaluate(val["offered"], pred)["biais_%"] < -2