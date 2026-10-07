from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from crc.app.alerts import build_alerts, interval_levels, message
from crc.app.explain import contributions, explain_interval
from crc.forecasting.features import build_features
from crc.forecasting.ml import SHAPE_FEATURES, HybridForecaster

DASHBOARD = Path(__file__).resolve().parents[1] / "src" / "crc" / "app" / "dashboard.py"


def test_alert_levels_combine_risk_and_anomalies():
    idx = pd.date_range("2024-12-02 08:00", periods=4, freq="30min")
    p = pd.Series([0.05, 0.12, 0.25, 0.05], index=idx)
    anomaly = pd.Series([0, 0, 0, 2], index=idx)
    assert list(interval_levels(p, anomaly)) == [0, 1, 2, 2]


def test_alerts_group_consecutive_intervals_and_recommend_reinforcement():
    idx = pd.date_range("2024-12-02 14:00", periods=5, freq="30min")
    level = pd.Series([0, 2, 2, 0, 1], index=idx)
    p = pd.Series([0.05, 0.22, 0.24, 0.05, 0.12], index=idx)
    loss = pd.Series([10.0, 300.0, 320.0, 10.0, 80.0], index=idx)
    applied = pd.Series([20, 30, 30, 25, 22], index=idx)
    optimal = pd.Series([20, 34, 36, 25, 23], index=idx)
    alerts = build_alerts(level, p, loss, applied, optimal)
    high = alerts[alerts["niveau"] == "Eleve"].iloc[0]
    assert high["debut"] == idx[1] and high["fin"] == idx[3]          # 14h30 - 15h30
    assert high["renfort_recommande"] == 6 and high["perte_attendue"] == 620
    text = message(high)
    assert "14h30 - 15h30" in text and "24 %" in text and "+6 agents" in text


def test_shap_contributions_rebuild_the_forecast(simulated):
    """Les contributions SHAP doivent expliquer EXACTEMENT la prevision, sans reste."""
    history, events, _ = simulated
    X = build_features(history, events)
    model = HybridForecaster().fit(history, X, events, pd.Timestamp("2024-07-01"))
    sample = X.loc["2024-09-02"]
    raw = model.model.predict(sample[SHAPE_FEATURES], pred_contrib=True)
    rebuilt = np.exp(raw.sum(axis=1)) * model.level.loc[sample.index].clip(lower=0.5)
    assert np.allclose(rebuilt, model.predict(X).loc[sample.index])
    effects = contributions(model, sample)
    assert "heure de la journee" in effects.columns
    top = explain_interval(model, X, pd.Timestamp("2024-09-02 10:30"))
    assert top["effet %"].abs().is_monotonic_decreasing


@pytest.mark.skipif(not (Path("data/app/jours.parquet").exists()), reason="lancer python -m crc.app.prepare")
def test_dashboard_pages_run_without_error():
    from streamlit.testing.v1 import AppTest
    for page in ["Vue d'ensemble", "Prevision", "Risque et planning", "What-if"]:
        at = AppTest.from_file(str(DASHBOARD), default_timeout=180)
        at.run()
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception, page