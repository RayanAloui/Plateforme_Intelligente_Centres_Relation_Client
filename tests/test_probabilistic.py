import numpy as np
import pandas as pd
import pytest

from crc.forecasting.probabilistic import CoxPredictive, poisson_quantiles


@pytest.fixture(scope="module")
def synthetic():
    """Donnees tirees d'un modele de Cox aux parametres CONNUS."""
    rng = np.random.default_rng(0)
    idx = pd.date_range("2023-01-01", periods=48 * 365, freq="30min")
    mu = pd.Series(80 + 70 * np.sin(np.arange(len(idx)) * 2 * np.pi / 48) ** 2, index=idx)
    dates = pd.Series(idx.date, index=idx)
    true = CoxPredictive(day_sigma=0.08, gamma_shape=40.0)
    y = pd.Series(true.sample(mu, dates, 1, rng)[0].astype(float), index=idx)
    return mu, dates, y


def test_calibration_recovers_known_parameters(synthetic):
    mu, dates, y = synthetic
    est = CoxPredictive.calibrate(mu, y, dates)
    assert est.day_sigma == pytest.approx(0.08, rel=0.2)
    assert est.gamma_shape == pytest.approx(40.0, rel=0.2)


def test_scenarios_share_the_day_error(synthetic):
    """Dans un meme scenario, un jour plus charge que prevu l'est toute la journee."""
    mu, dates, _ = synthetic
    big = mu.iloc[:48] * 100                     # gros volumes : le hasard de Poisson devient negligeable
    sims = CoxPredictive(0.08, 1e6).sample(big, dates.iloc[:48], 4000, np.random.default_rng(1))
    ratio = sims / big.to_numpy()
    assert np.corrcoef(ratio[:, 10], ratio[:, 30])[0, 1] > 0.5


def test_quantiles_ordered_and_wider_than_poisson(synthetic):
    mu, dates, _ = synthetic
    q = CoxPredictive(0.08, 40.0).quantiles(mu.iloc[:480], dates.iloc[:480], (0.1, 0.5, 0.9), n=500)
    assert (q[0.1] <= q[0.5]).all() and (q[0.5] <= q[0.9]).all()
    qp = poisson_quantiles(mu.iloc[:480], (0.1, 0.9))
    assert ((q[0.9] - q[0.1]) > (qp[0.9] - qp[0.1])).mean() > 0.9