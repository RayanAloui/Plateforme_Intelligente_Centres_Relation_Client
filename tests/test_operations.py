from datetime import date

import pandas as pd
import pytest

from crc.datagen.calendar import build_calendar
from crc.datagen.demand import generate_demand
from crc.datagen.events import generate_events
from crc.datagen.operations import simulate_operations
from crc.datagen.params import GeneratorParams
from crc.datagen.rng import make_rngs


@pytest.fixture(scope="module")
def ops():
    cal = build_calendar(date(2022, 1, 1), date(2024, 12, 31), 30)
    p = GeneratorParams()
    rngs = make_rngs(42)
    end = cal["ts"].iloc[-1] + pd.Timedelta(minutes=30)
    ev = generate_events(cal["ts"].iloc[0], end, p.events, rngs["events"])
    d = generate_demand(cal, ev, p.demand, rngs)
    return d, simulate_operations(cal, d, p.operations, rngs)


def test_schema_constraints_hold(ops):
    _, o = ops
    assert (o["answered"] + o["abandoned"] <= o["offered"]).all()
    assert (o["agents_scheduled"] >= o["agents_present"]).all()
    assert (o["avg_handle_seconds"] > 0).all()
    assert o["service_level"].between(0, 1).all()
    assert o["occupancy"].between(0, 1).all()


def test_realistic_global_kpis(ops):
    _, o = ops
    w = o["offered"]
    assert 0.02 < o["abandoned"].sum() / w.sum() < 0.10
    assert 0.75 < (o["service_level"] * w).sum() / w.sum() < 0.92


def test_incidents_degrade_service(ops):
    d, o = ops
    inc = d["is_incident"].to_numpy()
    assert o["service_level"][inc].mean() < o["service_level"][~inc].mean() - 0.2


def test_kpis_are_causally_linked(ops):
    _, o = ops
    assert o["avg_wait_seconds"].corr(o["service_level"]) < -0.5
    assert o["avg_wait_seconds"].corr(o["csat_mean"]) < -0.3