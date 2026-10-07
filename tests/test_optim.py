import numpy as np
import pandas as pd
import pytest

from crc.forecasting.probabilistic import CoxPredictive
from crc.optim.staffing import (budget_plan, build_curves, deterministic_plan, evaluate_plan,
                                risk_aware_plan, staff_cost)
from crc.optim.whatif import Scenario, what_if
from crc.queueing.erlang import erlang_a_metrics
from crc.risk.costs import DEFAULT_COSTS
from crc.risk.simulation import OperationalRiskModel

COSTS = DEFAULT_COSTS


@pytest.fixture(scope="module")
def day():
    idx = pd.date_range("2024-03-11", periods=48, freq="30min")
    hours = idx.hour + idx.minute / 60
    mu = pd.Series(20 + 180 * np.exp(-0.5 * ((hours - 11) / 3) ** 2), index=idx)
    aht = pd.Series(300.0, index=idx)
    model = OperationalRiskModel(CoxPredictive(0.08, 50), np.array([0.04, 0.06, 0.07, 0.25]), 180, COSTS)
    center = deterministic_plan(mu, aht, 0.06, 180, COSTS)
    return mu, aht, model, center, build_curves(model, mu, aht, center, n_scenarios=80)


def test_deterministic_plan_reaches_target_on_forecast(day):
    mu, aht, _, center, _ = day
    present = np.floor(center * (1 - 0.06)).astype(int)
    sl = erlang_a_metrics(present, mu.to_numpy() / 1800, aht.to_numpy(), 180, 20)["service_level"]
    assert (sl >= 0.85 - 0.02).all()


def test_risk_aware_plan_is_optimal_among_feasible(day):
    _, _, _, _, curves = day
    plan = risk_aware_plan(curves, COSTS, alpha=0.05)
    total = curves.staff + curves.loss
    feasible = (curves.sl >= 0.85) & (curves.undercap <= 0.05)
    rows = np.arange(len(plan))
    chosen = np.array([np.flatnonzero(curves.n[t] == plan[t])[0] for t in rows])
    for t in rows:
        if feasible[t].any():
            assert feasible[t, chosen[t]]
            assert total[t, chosen[t]] <= total[t][feasible[t]].min() + 1e-9


def test_tighter_risk_limit_costs_more(day):
    _, _, _, _, curves = day
    loose = risk_aware_plan(curves, COSTS, alpha=1.01)
    strict = risk_aware_plan(curves, COSTS, alpha=0.02)
    assert strict.sum() >= loose.sum()


def test_budget_plan_respects_budget(day):
    _, _, _, _, curves = day
    full = curves.n[:, -1]
    budget = 0.9 * staff_cost(full, COSTS).sum()
    plan = budget_plan(curves, budget)
    assert staff_cost(plan, COSTS).sum() <= budget + 1e-6


def test_more_agents_cost_more_but_lose_less(day):
    mu, aht, _, center, _ = day
    absence = pd.Series(0.06, index=mu.index)
    small = evaluate_plan(center, mu.round(), aht, absence, 180, COSTS)
    big = evaluate_plan(center + 3, mu.round(), aht, absence, 180, COSTS)
    assert big["cout_agents"].sum() > small["cout_agents"].sum()
    assert big["perte"].sum() < small["perte"].sum()


def test_what_if_reacts_to_manager_questions(day):
    mu, aht, model, _, _ = day
    ref = what_if(model, mu, aht, Scenario(), n_scenarios=60)
    busy = what_if(model, mu, aht, Scenario(volume_factor=1.2), n_scenarios=60)
    cut = what_if(model, mu, aht, Scenario(budget_cut=0.15), n_scenarios=60)
    assert busy["heures_agents"] > ref["heures_agents"]
    assert cut["cout_agents"] <= 0.85 * ref["cout_agents"] + 1e-6
    assert cut["perte_attendue"] > ref["perte_attendue"]       # le prix de l'economie