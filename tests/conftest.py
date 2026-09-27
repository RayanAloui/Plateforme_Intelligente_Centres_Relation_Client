"""Donnees simulees partagees par les tests, sans passer par la base."""
from datetime import date

import pandas as pd
import pytest

from crc.datagen.calendar import build_calendar
from crc.datagen.params import GeneratorParams
from crc.datagen.pipeline import generate
from crc.etl.clean import clean


@pytest.fixture(scope="session")
def simulated():
    """(historique au format load_history, evenements, verite terrain)."""
    cal = build_calendar(date(2022, 1, 1), date(2024, 12, 31), 30)
    events, acd, wfm, truth, _ = generate(cal, GeneratorParams(), seed=42, granularity=30)
    core, _ = clean(acd, wfm, pd.DatetimeIndex(cal["ts"]))
    history = core.merge(cal, on="ts").set_index("ts")
    return history, events, truth.set_index("ts")