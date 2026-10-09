import numpy as np
import pandas as pd
import pytest

import crc.optim.shifts as shifts_module
from crc.forecasting.probabilistic import CoxPredictive
from crc.ops.outlook import OFFSETS
from crc.optim.shifts import lower_hull, minimum_coverage, schedule_shifts, shift_lengths, shifts_frame
from crc.optim.staffing import build_curves, deterministic_plan
from crc.risk.costs import DEFAULT_COSTS
from crc.risk.simulation import OperationalRiskModel

COSTS = {**DEFAULT_COSTS, "shift_min_hours": 4, "max_shift_hours": 8, "shift_length_step_hours": 2}


@pytest.fixture(scope="module")
def curves():
    idx = pd.date_range("2025-03-10", periods=48, freq="30min")
    hours = idx.hour + idx.minute / 60
    mu = pd.Series(15 + 170 * np.exp(-0.5 * ((hours - 11) / 3.2) ** 2), index=idx)
    aht = pd.Series(300.0, index=idx)
    model = OperationalRiskModel(CoxPredictive(0.08, 50), np.array([0.05, 0.06, 0.07]), 180, COSTS)
    center = deterministic_plan(mu, aht, 0.06, 180, COSTS)
    return build_curves(model, mu, aht, center, n_scenarios=60, offsets=OFFSETS)


@pytest.fixture(autouse=True)
def quick_solver(monkeypatch):
    monkeypatch.setattr(shifts_module, "DETERMINISTIC_TIME", 1.0)


def test_lower_hull_keeps_only_the_convex_envelope():
    xs = np.array([10, 11, 12, 13, 14])
    ys = np.array([100, 60, 45, 30, 28])           # le point (12, 45) est au-dessus de l'enveloppe
    assert lower_hull(xs, ys) == [(10, 100), (11, 60), (13, 30), (14, 28)]


def test_allowed_lengths_come_from_parameters():
    assert shift_lengths(COSTS) == [4, 6, 8]
    assert shift_lengths({**COSTS, "shift_min_hours": 6}) == [6, 8]


def test_shifts_cover_the_risk_minimum_with_allowed_shapes(curves):
    sol = schedule_shifts(curves, COSTS, alpha=0.05)
    assert (sol.coverage >= minimum_coverage(curves, COSTS, 0.05)).all()
    assert (sol.coverage <= COSTS["agents_max_available"]).all()
    assert set(sol.shifts["duree_periodes"]) <= {8, 12, 16}         # 4 h, 6 h, 8 h
    assert (sol.shifts["debut_periode"] % 2 == 0).all()              # a l'heure pile
    frame = shifts_frame(sol, pd.Timestamp("2025-03-10"))
    assert (frame["fin"] > frame["debut"]).all()


def test_solution_is_reproducible(curves):
    a = schedule_shifts(curves, COSTS, alpha=0.05)
    b = schedule_shifts(curves, COSTS, alpha=0.05)
    assert np.array_equal(a.coverage, b.coverage)


def test_rigid_organisation_costs_more(curves):
    standard = schedule_shifts(curves, COSTS, alpha=0.05)
    rigid = schedule_shifts(curves, COSTS, alpha=0.05, lengths=[8])
    assert rigid.staff_cost + rigid.expected_loss >= standard.staff_cost + standard.expected_loss - 1
