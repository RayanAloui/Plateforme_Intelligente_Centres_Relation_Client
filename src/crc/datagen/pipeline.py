"""Generation complete, du calendrier jusqu'aux tables raw, en une commande.

    python -m crc.datagen.pipeline            # base de donnees + verite terrain
    python -m crc.datagen.pipeline --excel    # + copie Excel pour consultation

La base ne recoit que ce qu'un centre reel possederait : les exports bruts.
La verite terrain (intensites, defauts injectes) est rangee a part dans data/truth.
"""
import argparse
import time
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from crc.config import get_settings
from crc.datagen.demand import generate_demand
from crc.datagen.events import generate_events
from crc.datagen.imperfections import to_raw_exports
from crc.datagen.operations import simulate_operations
from crc.datagen.params import GeneratorParams
from crc.datagen.rng import make_rngs
from crc.db import get_engine, read_sql

TRUTH_DIR = Path("data/truth")
EXPORT_DIR = Path("data/exports")

OBSERVABLE = ["ts", "offered", "answered", "abandoned", "avg_wait_seconds",
              "avg_handle_seconds", "agents_scheduled", "agents_present", "agents_absent",
              "service_level", "abandon_rate", "occupancy", "csat_mean", "csat_responses"]


def generate(calendar: pd.DataFrame, params: GeneratorParams, seed: int, granularity: int):
    """Toute la recette : evenements -> demande -> operations -> exports bruts."""
    rngs = make_rngs(seed)
    start = calendar["ts"].iloc[0]
    end = calendar["ts"].iloc[-1] + pd.Timedelta(minutes=granularity)

    events = generate_events(start, end, params.events, rngs["events"], granularity)
    demand = generate_demand(calendar, events, params.demand, rngs, 24 * 60 // granularity)
    ops = simulate_operations(calendar, demand, params.operations, rngs, granularity * 60)
    acd, wfm, defects = to_raw_exports(ops[OBSERVABLE], params.defects, rngs["defects"])

    truth = demand.drop(columns="offered").merge(ops, on="ts")   # offered present des deux cotes
    return events, acd, wfm, truth, defects


def _write(df: pd.DataFrame, table: str, schema: str, conn) -> None:
    df.to_sql(table, conn, schema=schema, if_exists="append", index=False,
              method="multi", chunksize=2000)


def run(excel: bool = False) -> None:
    s = get_settings()
    engine = get_engine()
    t0 = time.perf_counter()

    calendar = read_sql("SELECT * FROM ref.calendar ORDER BY ts")
    if calendar.empty:
        raise SystemExit("ref.calendar est vide : lancer d'abord  python -m crc.datagen.calendar")

    with engine.begin() as conn:
        run_id = conn.execute(text(
            "INSERT INTO core.etl_runs (step_name, rows_in) VALUES ('datagen', :n) RETURNING run_id"
        ), {"n": len(calendar)}).scalar_one()

    try:
        events, acd, wfm, truth, defects = generate(
            calendar, GeneratorParams(), s.random_seed, s.time_granularity_minutes)

        # Une seule transaction : soit tout est charge, soit rien.
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE raw.acd_export, raw.wfm_roster, ref.events RESTART IDENTITY"))
            _write(events, "events", "ref", conn)
            _write(acd, "acd_export", "raw", conn)
            _write(wfm, "wfm_roster", "raw", conn)

        TRUTH_DIR.mkdir(parents=True, exist_ok=True)
        truth.to_parquet(TRUTH_DIR / "ground_truth.parquet", index=False)
        defects.to_parquet(TRUTH_DIR / "defects.parquet", index=False)

        if excel:
            EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            with pd.ExcelWriter(EXPORT_DIR / "historique_simule.xlsx") as xl:
                truth[OBSERVABLE].to_excel(xl, sheet_name="donnees", index=False)
                events.to_excel(xl, sheet_name="evenements", index=False)
                defects.groupby(["table", "defect"]).size().rename("nombre") \
                       .reset_index().to_excel(xl, sheet_name="defauts_injectes", index=False)

        message = f"{len(events)} evenements, {len(defects)} defauts injectes"
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE core.etl_runs SET finished_at = now(), rows_out = :n,
                       status = 'success', message = :m WHERE run_id = :id
            """), {"n": len(acd) + len(wfm), "m": message, "id": run_id})

    except Exception as exc:
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE core.etl_runs SET finished_at = now(), status = 'failed',
                       message = :m WHERE run_id = :id
            """), {"m": str(exc)[:500], "id": run_id})
        raise

    print(f"Generation terminee en {time.perf_counter() - t0:.1f} s")
    print(f"  ref.events      : {len(events):>6} evenements")
    print(f"  raw.acd_export  : {len(acd):>6} lignes")
    print(f"  raw.wfm_roster  : {len(wfm):>6} lignes")
    print(f"  defauts injectes: {len(defects):>6}  (detail dans {TRUTH_DIR / 'defects.parquet'})")
    if excel:
        print(f"  copie Excel     : {EXPORT_DIR / 'historique_simule.xlsx'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Genere l'historique simule du centre.")
    parser.add_argument("--excel", action="store_true", help="exporter aussi une copie Excel")
    run(parser.parse_args().excel)