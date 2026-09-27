import pandas as pd
import pytest

from crc.forecasting.features import build_features
from crc.forecasting.intervals import rolling_forecast
from crc.forecasting.registry import build_bundle, future_frame, load_bundle, save_bundle

CUTOFF = pd.Timestamp("2024-07-01")


@pytest.fixture(scope="module")
def bundle(simulated):
    history, events, _ = simulated
    X = build_features(history, events)
    rolling = rolling_forecast(history, events, X, pd.Timestamp("2024-05-01"), CUTOFF)
    return build_bundle(history, events, X, CUTOFF, rolling, fingerprint="test")


def test_save_and_reload_give_identical_forecasts(bundle, simulated, tmp_path):
    history, events, _ = simulated
    X = build_features(history, events)
    save_bundle(bundle, tmp_path)
    reloaded = load_bundle(directory=tmp_path)
    a = bundle.forecast(history, events, X)["volume_attendu"]
    b = reloaded.forecast(history, events, X)["volume_attendu"]
    pd.testing.assert_series_equal(a, b)
    assert (tmp_path / f"{bundle.version}.json").exists()


def test_forecasts_a_day_beyond_the_data(bundle, simulated):
    """Le modele sauvegarde sait prevoir un jour qui n'existe pas encore dans les donnees."""
    history, events, _ = simulated
    extended = future_frame(history, days=1)
    X = build_features(extended, events)
    fc = bundle.forecast(extended, events, X).loc[extended.index > history.index[-1]]
    assert len(fc) == 48
    assert fc["volume_attendu"].between(1, 1000).all()
    assert fc["aht_attendue"].between(100, 600).all()


def test_card_documents_the_model(bundle):
    card = bundle.card
    assert card["donnees"]["coupure"] == "2024-07-01"
    assert abs(card["performances_hors_echantillon"]["biais_%"]) < 2
    assert card["periode_de_test"].startswith("non evaluee")