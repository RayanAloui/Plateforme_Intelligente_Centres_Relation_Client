import numpy as np
import pandas as pd
import pytest
from scipy import stats

from crc.forecasting.probabilistic import CoxPredictive
from crc.risk.costs import DEFAULT_COSTS, estimate_patience, observed_losses, queue_losses
from crc.risk.lda import compound_losses, extract_events, fit_frequency, fit_severity
from crc.risk.simulation import OperationalRiskModel, expected_shortfall, kupiec_test, var
from crc.splits import select


def test_patience_is_recovered_from_history(simulated):
    """Le generateur utilise une patience de 180 s : l'estimation doit la retrouver."""
    history, _, _ = simulated
    assert estimate_patience(select(history, "train")) == pytest.approx(180, abs=20)


def test_observed_losses_add_up(simulated):
    history, _, _ = simulated
    L = observed_losses(history.iloc[:500], DEFAULT_COSTS)
    assert np.allclose(L["perte"], L["attente"] + L["abandons"] + L["penalite"])
    assert (L >= 0).all().all()


def test_more_agents_means_less_loss():
    arrivals = np.full((1, 3), 150.0)
    aht = np.full((1, 3), 300.0)
    few = queue_losses(arrivals, np.full((1, 3), 22), aht, 180, DEFAULT_COSTS)["perte"].sum()
    many = queue_losses(arrivals, np.full((1, 3), 30), aht, 180, DEFAULT_COSTS)["perte"].sum()
    assert many < few


def test_risk_measures_are_ordered():
    losses = np.random.default_rng(0).lognormal(8, 0.6, 10_000)
    assert losses.mean() < var(losses, 0.95) < expected_shortfall(losses, 0.95) < expected_shortfall(losses, 0.99)


def test_staffing_reduces_daily_risk():
    idx = pd.date_range("2024-03-11", periods=48, freq="30min")
    mu = pd.Series(np.where((idx.hour >= 8) & (idx.hour < 20), 180.0, 20.0), index=idx)
    aht = pd.Series(300.0, index=idx)
    model = OperationalRiskModel(CoxPredictive(0.08, 50), np.array([0.05, 0.06, 0.08]), 180, DEFAULT_COSTS)
    tight = model.day_risk(mu, aht, np.where(mu > 100, 30, 4), n=400)
    safe = model.day_risk(mu, aht, np.where(mu > 100, 38, 6), n=400)
    assert safe["perte_attendue"] < tight["perte_attendue"]
    assert safe["VaR95"] < tight["VaR95"]
    assert safe["cout_agents"] > tight["cout_agents"]          # le compromis cout / risque


def test_kupiec_accepts_good_and_rejects_bad_var():
    assert kupiec_test(9, 182, 0.95) > 0.5        # 4,9 % de depassements pour 5 % attendus
    assert kupiec_test(30, 182, 0.95) < 0.01      # 16 % : VaR beaucoup trop optimiste


def test_events_are_runs_of_consecutive_intervals():
    idx = pd.date_range("2024-01-01", periods=8, freq="30min")
    mask = pd.Series([False, True, True, False, True, False, False, True], index=idx)
    ev = extract_events(mask, pd.Series(10.0, index=idx), daily=False)
    assert list(ev["duree"]) == [2, 1, 1] and list(ev["severite"]) == [20, 10, 10]


def test_frequency_law_detects_overdispersion():
    rng = np.random.default_rng(0)
    assert fit_frequency(rng.poisson(10, 60))["loi"] == "Poisson"
    assert fit_frequency(rng.negative_binomial(2, 2 / 12, 60))["loi"] == "binomiale negative"


def test_severity_fit_recovers_lognormal_and_compound_mean():
    rng = np.random.default_rng(0)
    x = rng.lognormal(6, 0.8, 3000)
    fits = fit_severity(x)
    assert fits.iloc[0]["loi"] == "lognormale"
    freq = fit_frequency(rng.poisson(5, 60))
    monthly = compound_losses(freq, stats.lognorm, fits.iloc[0]["params"], n=20_000)
    assert monthly.mean() == pytest.approx(freq["moyenne"] * x.mean(), rel=0.05)   # E[L] = E[N] E[S]