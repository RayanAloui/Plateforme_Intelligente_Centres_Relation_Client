"""Chargement de core.interval_metrics a partir des tables raw.

    python -m crc.etl.pipeline
"""
import time
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from crc.db import get_engine, read_sql
from crc.etl.clean import clean
from crc.etl.quality import quality_report

TRUTH_DIR = Path("data/truth")
REPORT_DIR = Path("data/reports")

CORE_COLUMNS = ["ts", "offered", "answered", "abandoned", "avg_wait_seconds",
                "avg_handle_seconds", "agents_scheduled", "agents_present", "agents_absent",
                "service_level", "abandon_rate", "occupancy", "csat_mean", "csat_responses",
                "is_imputed", "imputed_columns"]


def run() -> None:
    engine = get_engine()
    t0 = time.perf_counter()

    grid = pd.DatetimeIndex(read_sql("SELECT ts FROM ref.calendar ORDER BY ts")["ts"])
    acd = read_sql("SELECT * FROM raw.acd_export ORDER BY id")
    wfm = read_sql("SELECT * FROM raw.wfm_roster ORDER BY id")
    if acd.empty:
        raise SystemExit("raw.acd_export est vide : lancer d'abord  python -m crc.datagen.pipeline")

    with engine.begin() as conn:
        run_id = conn.execute(text(
            "INSERT INTO core.etl_runs (step_name, rows_in) VALUES ('etl_core', :n) RETURNING run_id"
        ), {"n": len(acd) + len(wfm)}).scalar_one()

    try:
        core, report = clean(acd, wfm, grid)
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE core.interval_metrics"))
            core[CORE_COLUMNS].to_sql("interval_metrics", conn, schema="core", if_exists="append",
                                      index=False, method="multi", chunksize=2000)
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE core.etl_runs SET finished_at = now(), rows_out = :n,
                       status = 'success', message = :m WHERE run_id = :id
            """), {"n": len(core), "m": str(report), "id": run_id})
    except Exception as exc:
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE core.etl_runs SET finished_at = now(), status = 'failed',
                       message = :m WHERE run_id = :id
            """), {"m": str(exc)[:500], "id": run_id})
        raise

    print(f"core.interval_metrics : {len(core)} intervalles charges en "
          f"{time.perf_counter() - t0:.1f} s")
    for key, value in report.items():
        print(f"  {key:<28} {value:>6}")

    # Evaluation contre la verite terrain (disponible uniquement parce que les donnees sont simulees)
    if (TRUTH_DIR / "ground_truth.parquet").exists():
        q = quality_report(core, pd.read_parquet(TRUTH_DIR / "ground_truth.parquet"),
                           pd.read_parquet(TRUTH_DIR / "defects.parquet"), report)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        q.to_csv(REPORT_DIR / "etl_quality.csv", index=False)
        print("\nQualite du nettoyage (comparaison a la verite terrain) :")
        print(q.to_string(index=False))


if __name__ == "__main__":
    run()