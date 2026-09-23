from datetime import date

import numpy as np
import pandas as pd
import pytest

from crc.datagen.calendar import build_calendar
from crc.datagen.demand import annual_profile, generate_demand, intraday_profile
from crc.datagen.events import generate_events
from crc.datagen.params import GeneratorParams
from crc.datagen.rng import make_rngs


def _run(seed=42):
    cal = build_calendar(date(2022, 1, 1), date(2024, 12, 31), 30)
    p = GeneratorParams()
    rngs = make_rngs(seed)
    end = cal["ts"].iloc[-1] + pd.Timedelta(minutes=30)
    ev = generate_events(cal["ts"].iloc[0], end, p.events, rngs["events"])
    return cal, ev, generate_demand(cal, ev, p.demand, rngs)


@pytest.fixture(scope="module")
def generated():
    return _run()


def test_reproducible():
    _, _, a = _run(7)
    _, _, b = _run(7)
    assert np.array_equal(a["offered"], b["offered"])


def test_profiles_are_normalized():
    p = GeneratorParams().demand
    assert intraday_profile(p.weekday_bumps, p.night_floor, 48).mean() == pytest.approx(1.0)
    doy = np.arange(1, 366)
    assert annual_profile(doy, p.monthly_profile).mean() == pytest.approx(1.0, abs=0.01)


def test_weekday_busier_than_weekend(generated):
    cal, _, d = generated
    weekend = cal["is_weekend"].to_numpy()
    assert d["offered"][~weekend].mean() > 1.3 * d["offered"][weekend].mean()


def test_growth_over_years(generated):
    cal, _, d = generated
    totals = d.groupby(cal["year"].to_numpy())["offered"].sum()
    assert totals.is_monotonic_increasing


def test_overdispersion(generated):
    _, _, d = generated
    residual = d["offered"] - d["lambda_true"]
    assert residual.var() > d["lambda_true"].mean()   # plus disperse que Poisson


def test_events_raise_intensity(generated):
    _, ev, d = generated
    assert len(ev) > 0
    assert (d["event_multiplier"] >= 1).all()
    assert d.loc[d["is_incident"], "aht_seconds"].mean() > d.loc[~d["is_incident"], "aht_seconds"].mean()