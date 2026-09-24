import math

import numpy as np
import pytest

from crc.queueing.erlang import (erlang_a_metrics, erlang_c_required_agents,
                                 erlang_c_service_level, erlang_c_wait_prob)


def _erlang_c_reference(n, a):
    """Formule directe, pour verifier la recurrence."""
    s = sum(a**k / math.factorial(k) for k in range(n))
    t = a**n / math.factorial(n) * n / (n - a)
    return t / (s + t)


@pytest.mark.parametrize("n", [11, 13, 15, 20])
def test_erlang_c_matches_closed_form(n):
    got = erlang_c_wait_prob(np.array([n]), np.array([10.0]))[0]
    assert got == pytest.approx(_erlang_c_reference(n, 10.0), rel=1e-9)


def test_erlang_c_unstable_when_overloaded():
    assert erlang_c_wait_prob(np.array([10]), np.array([12.0]))[0] == 1.0


def test_required_agents_reach_target():
    a = np.array([5.0, 20.0, 44.0])
    aht = np.full(3, 300.0)
    n = erlang_c_required_agents(a, aht, 20, 0.8)
    assert (erlang_c_service_level(n, a, aht, 20) >= 0.8).all()
    assert (erlang_c_service_level(n - 1, a, aht, 20) < 0.8).all()


def test_erlang_a_converges_to_erlang_c():
    m = erlang_a_metrics(np.array([13]), np.array([100 / 1800]), np.array([180.0]), 1e9, 20)
    assert m["service_level"][0] == pytest.approx(erlang_c_service_level(13, 10.0, 180, 20), abs=1e-6)


def test_erlang_a_defined_under_overload():
    m = erlang_a_metrics(np.array([10]), np.array([12 / 300]), np.array([300.0]), 180, 20)
    assert 0 < m["abandon_prob"][0] < 1
    assert 0 <= m["service_level"][0] < 0.8