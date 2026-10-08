"""Import d'une journee : exports bruts -> raw -> nettoyage -> core.

C'est le meme nettoyage que l'etape 1.4 (crc.etl.clean), applique a une seule journee :
dates relues, doublons supprimes, valeurs impossibles corrigees, trous reconstitues.
"""
import shutil
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from crc.datagen.calendar import build_calendar
from crc.db import get_engine
from crc.etl.clean import clean
from crc.ops.simulator import INBOX_DIR

CORE_COLUMNS = ["ts", "offered", "answered", "abandoned", "avg_wait_seconds", "avg_handle_seconds",
                "agents_scheduled", "agents_present", "agents_absent", "service_level", "abandon_rate",
                "occupancy", "csat_mean", "csat_responses", "is_imputed", "imputed_columns"]


def ensure_calendar(start: date, end: date, granularity: int = 30) -> int:
    """Ajoute a ref.calendar les jours manquants (sans toucher aux existants)."""
    cal = build_calendar(start, end, granularity)
    with get_engine().begin() as conn:
        existing = {r[0] for r in conn.execute(
            text("SELECT ts FROM ref.calendar WHERE ts BETWEEN :a AND :b"),
            {"a": cal["ts"].iloc[0], "b": cal["ts"].iloc[-1]})}
        missing = cal[~cal["ts"].isin(existing)]
        if len(missing):
            missing.to_sql("calendar", conn, schema="ref", if_exists="append", index=False)
    return len(missing)


def import_day(day: date, inbox: Path = INBOX_DIR) -> dict:
    """Importe les exports ACD et WFM du jour, nettoie, et ecrit la journee dans core."""
    acd_path, wfm_path = inbox / f"acd_{day:%Y%m%d}.csv", inbox / f"wfm_{day:%Y%m%d}.csv"
    if not acd_path.exists() or not wfm_path.exists():
        raise FileNotFoundError(f"Exports du {day:%d/%m/%Y} absents de {inbox}")
    acd = pd.read_csv(acd_path, dtype={"ts_text": str})
    wfm = pd.read_csv(wfm_path, dtype={"ts_text": str})

    ensure_calendar(day, day + timedelta(days=1))
    grid = pd.date_range(pd.Timestamp(day), periods=48, freq="30min")
    core, report = clean(acd, wfm, grid)

    with get_engine().begin() as conn:
        acd.assign(source_file=acd_path.name).to_sql("acd_export", conn, schema="raw", if_exists="append", index=False)
        wfm.assign(source_file=wfm_path.name).to_sql("wfm_roster", conn, schema="raw", if_exists="append", index=False)
        conn.execute(text("DELETE FROM core.interval_metrics WHERE ts >= :a AND ts < :b"),
                     {"a": grid[0], "b": grid[-1] + pd.Timedelta(minutes=30)})
        core[CORE_COLUMNS].to_sql("interval_metrics", conn, schema="core", if_exists="append", index=False)

    archive = inbox / "archive"
    archive.mkdir(exist_ok=True)
    for path in (acd_path, wfm_path):
        shutil.move(str(path), archive / path.name)
    report.update({"lignes_acd": len(acd), "lignes_wfm": len(wfm), "appels": int(core["offered"].sum())})
    return report


def record_events(events: pd.DataFrame) -> int:
    """Enregistre des evenements dans ref.events, sans doublon."""
    if events.empty:
        return 0
    added = 0
    with get_engine().begin() as conn:
        for ev in events.itertuples():
            exists = conn.execute(text("SELECT 1 FROM ref.events WHERE start_ts = :s AND event_type = :t"),
                                  {"s": ev.start_ts, "t": ev.event_type}).first()
            if not exists:
                conn.execute(text("INSERT INTO ref.events (start_ts, end_ts, event_type, intensity, description) "
                                  "VALUES (:s, :e, :t, :i, :d)"),
                             {"s": ev.start_ts, "e": ev.end_ts, "t": ev.event_type,
                              "i": float(ev.intensity), "d": ev.description})
                added += 1
    return added
