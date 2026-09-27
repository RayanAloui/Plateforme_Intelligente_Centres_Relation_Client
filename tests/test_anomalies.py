import numpy as np
import pandas as pd

from crc.forecasting.anomalies import AnomalyDetector, evaluate_rule
from crc.forecasting.probabilistic import CoxPredictive


def test_injected_spike_is_flagged_as_strong():
    rng = np.random.default_rng(0)
    idx = pd.date_range("2024-01-01", periods=48 * 7, freq="30min")
    mu = pd.Series(100.0, index=idx)
    dates = pd.Series(idx.date, index=idx)
    model = CoxPredictive(day_sigma=0.08, gamma_shape=50.0)
    y = pd.Series(model.sample(mu, dates, 1, rng)[0].astype(float), index=idx)
    y.iloc[200] = 300                                  # pic d'incident : x3
    res = AnomalyDetector(model).detect(mu, y, dates, n=4000)
    assert res["niveau"].iloc[200] == 2
    assert (res["niveau"] == 2).mean() < 0.01          # tres peu d'alertes fortes ailleurs


def test_evaluate_rule_counts_detections_and_false_alarms():
    idx = pd.date_range("2024-01-01", periods=10, freq="30min")
    flag = pd.Series([False, True, False, False, False, False, False, True, False, False], index=idx)
    incidents = pd.DataFrame({"start_ts": [idx[1], idx[4]], "end_ts": [idx[3], idx[6]]})
    excess = pd.Series([150.0, 20.0])
    r = evaluate_rule(flag, incidents, excess, weeks=1)
    assert r["incidents detectes %"] == 50                # 1 incident sur 2
    assert r["incidents a fort impact detectes %"] == 100
    assert r["fausses alertes / semaine"] == 1            # l'alerte de idx[7]