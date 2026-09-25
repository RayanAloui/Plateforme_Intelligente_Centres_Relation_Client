from datetime import date

import pandas as pd
import pytest

import crc.eda.report as report
from crc.datagen.calendar import build_calendar
from crc.datagen.params import GeneratorParams
from crc.datagen.pipeline import generate
from crc.etl.clean import clean


@pytest.fixture(scope="module")
def history():
    """Meme structure que load_history(), sans passer par la base."""
    cal = build_calendar(date(2023, 1, 1), date(2024, 12, 31), 30)
    _, acd, wfm, _, _ = generate(cal, GeneratorParams(), seed=1, granularity=30)
    core, _ = clean(acd, wfm, pd.DatetimeIndex(cal["ts"]))
    return core.merge(cal, on="ts").set_index("ts")


def test_report_produces_all_figures(history, tmp_path, monkeypatch):
    monkeypatch.setattr(report, "OUT", tmp_path)
    report.fig_tendance(history)
    report.fig_profil_intrajournalier(history)
    report.fig_saisonnalite(history)
    acf = report.fig_autocorrelation(history)
    report.fig_charge_vs_service(history)
    report.fig_correlations(history)
    disp = report.fig_dispersion(history)
    assert len(list(tmp_path.glob("*.png"))) == 7
    assert acf[336] > acf[48] > 0.5          # memoire hebdomadaire plus forte que journaliere
    assert disp > 1                          # surdispersion
    kf = report.key_figures(history, acf, disp)
    assert len(kf) == 11