import pandas as pd

from crc.forecasting.baselines import baselines
from crc.forecasting.features import FEATURES, build_features
from crc.forecasting.metrics import evaluate
from crc.splits import select


def test_no_data_leakage(simulated):
    """Modifier le jour D et la suite ne doit changer AUCUNE variable du jour D.

    C'est la preuve que la prevision du jour D n'utilise que le passe.
    """
    history, events, _ = simulated
    day = pd.Timestamp("2024-03-12")
    X = build_features(history, events)

    altered = history.copy()
    altered.loc[altered.index >= day, "offered"] *= 3
    X_alt = build_features(altered, events)

    same_day = (X.index >= day) & (X.index < day + pd.Timedelta(days=1))
    pd.testing.assert_frame_equal(X[same_day], X_alt[same_day])


def test_features_complete_after_warmup(simulated):
    history, events, _ = simulated
    X = select(build_features(history, events), "validation", "test")
    assert list(X.columns) == FEATURES
    assert X.notna().all().all()


def test_campaigns_are_flagged(simulated):
    history, events, _ = simulated
    X = build_features(history, events)
    camp = events[events["event_type"] == "campagne_commerciale"].iloc[0]
    assert X.loc[camp["start_ts"], "campaign"] == 1


def test_metrics_on_perfect_forecast():
    y = pd.Series([10.0, 20.0, 30.0])
    m = evaluate(y, y)
    assert m["MAE"] == m["RMSE"] == m["WAPE_%"] == m["biais_%"] == 0


def test_baselines_beaten_by_oracle(simulated):
    history, events, truth = simulated
    val = select(history, "validation")
    val = val[~val["is_imputed"]]
    X = build_features(history, events)
    oracle = evaluate(val["offered"], truth.loc[val.index, "lambda_true"])["WAPE_%"]
    for pred in baselines(X).values():
        assert evaluate(val["offered"], pred.reindex(val.index))["WAPE_%"] > oracle