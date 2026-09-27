"""Reconstruit toute la Phase 1 depuis zero, en une commande.

    python -m crc.rebuild            # calendrier -> generation -> nettoyage -> EDA
    python -m crc.rebuild --excel    # + copie Excel des donnees

L'empreinte affichee a la fin resume le contenu exact de core.interval_metrics :
deux executions qui affichent la meme empreinte ont produit les memes donnees.
"""
import argparse
import hashlib
import time

from crc.datagen.calendar import load_calendar
from crc.datagen.pipeline import run as run_datagen
from crc.db import read_sql
from crc.eda.report import run as run_eda
from crc.etl.pipeline import run as run_etl


def fingerprint() -> str:
    core = read_sql("SELECT * FROM core.interval_metrics ORDER BY ts")
    csv = core.to_csv(index=False, float_format="%.4f")
    return hashlib.sha256(csv.encode()).hexdigest()[:12]


def main(excel: bool) -> None:
    t0 = time.perf_counter()
    steps = [
        ("1/4 Calendrier", lambda: print(f"ref.calendar : {load_calendar()} intervalles")),
        ("2/4 Generation", lambda: run_datagen(excel)),
        ("3/4 Nettoyage", run_etl),
        ("4/4 Analyse exploratoire", run_eda),
    ]
    for title, step in steps:
        print(f"\n=== {title} " + "=" * (50 - len(title)))
        step()
    print(f"\nPhase 1 reconstruite en {time.perf_counter() - t0:.0f} s")
    print(f"Empreinte des donnees : {fingerprint()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reconstruit toute la Phase 1.")
    parser.add_argument("--excel", action="store_true", help="exporter aussi une copie Excel")
    main(parser.parse_args().excel)