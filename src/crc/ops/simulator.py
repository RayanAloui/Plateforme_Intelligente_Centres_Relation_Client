"""Simulateur d'exploitation : le monde continue apres 2024.

Les systemes d'un vrai centre (distributeur d'appels ACD, outil de gestion des effectifs WFM)
deposent chaque nuit leurs exports de la veille. Ce module joue leur role pour la demonstration :
il simule 2025-2026 avec le meme generateur que l'historique (la croissance continue, les
saisons, les incidents, les absences), puis "livre" les fichiers jour apres jour dans
data/inbox/, exactement comme le ferait un systeme reel.

    data/future/   le monde futur complet, cache (jamais lu par les modeles)
    data/inbox/    les exports deposes, en attente d'import
"""
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from crc.datagen.calendar import build_calendar
from crc.datagen.demand import generate_demand
from crc.datagen.events import generate_events
from crc.datagen.imperfections import to_raw_exports
from crc.datagen.operations import simulate_operations
from crc.datagen.params import GeneratorParams
from crc.datagen.pipeline import OBSERVABLE
from crc.datagen.rng import make_rngs
from crc.etl.clean import parse_timestamps

FUTURE_DIR = Path("data/future")
INBOX_DIR = Path("data/inbox")
FUTURE_START, FUTURE_END = date(2025, 1, 1), date(2026, 12, 31)
HISTORY_ORIGIN = pd.Timestamp("2022-01-01")       # la tendance continue depuis le debut de l'historique
SEED_OFFSET = 1000                                # un monde futur distinct, mais reproductible


def generate_future(seed: int, start: date = FUTURE_START, end: date = FUTURE_END, granularity: int = 30) -> dict:
    """Monde futur complet : evenements, exports bruts (avec defauts) et verite terrain."""
    params = GeneratorParams()
    rngs = make_rngs(seed + SEED_OFFSET)
    cal = build_calendar(start, end, granularity)
    t0, t1 = cal["ts"].iloc[0], cal["ts"].iloc[-1] + pd.Timedelta(minutes=granularity)
    events = generate_events(t0, t1, params.events, rngs["events"], granularity)
    demand = generate_demand(cal, events, params.demand, rngs, 24 * 60 // granularity, origin=HISTORY_ORIGIN)
    ops = simulate_operations(cal, demand, params.operations, rngs, granularity * 60)
    acd, wfm, _ = to_raw_exports(ops[OBSERVABLE], params.defects, rngs["defects"])
    acd["jour"] = parse_timestamps(acd["ts_text"]).dt.date
    wfm["jour"] = parse_timestamps(wfm["ts_text"]).dt.date
    truth = demand.drop(columns="offered").merge(ops, on="ts")
    return {"events": events, "acd": acd, "wfm": wfm, "truth": truth}


def prepare_future(seed: int, directory: Path = FUTURE_DIR) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, frame in generate_future(seed).items():
        frame.to_parquet(directory / f"{name}.parquet", index=False)


def is_prepared(directory: Path = FUTURE_DIR) -> bool:
    return all((directory / f"{n}.parquet").exists() for n in ("events", "acd", "wfm", "truth"))


def load_future(name: str, directory: Path = FUTURE_DIR) -> pd.DataFrame:
    return pd.read_parquet(directory / f"{name}.parquet")


def planned_campaigns(directory: Path = FUTURE_DIR) -> pd.DataFrame:
    """Campagnes commerciales futures : le marketing les communique a l'avance."""
    ev = load_future("events", directory)
    return ev[ev["event_type"] == "campagne_commerciale"]


def incidents_of(day: date, directory: Path = FUTURE_DIR) -> pd.DataFrame:
    """Incidents survenus ce jour-la : connus seulement apres coup."""
    ev = load_future("events", directory)
    start = pd.Timestamp(day)
    return ev[(ev["event_type"] == "incident_technique") & (ev["start_ts"] >= start)
              & (ev["start_ts"] < start + pd.Timedelta(days=1))]


def release_day(day: date, directory: Path = FUTURE_DIR, inbox: Path = INBOX_DIR) -> list[Path]:
    """Depose dans la boite de reception les exports de la journee `day`, et le planning
    WFM deja prevu pour le lendemain (le planning "actuel", celui de l'outil en place)."""
    inbox.mkdir(parents=True, exist_ok=True)
    acd, wfm, truth = (load_future(n, directory) for n in ("acd", "wfm", "truth"))
    if day not in set(acd["jour"]):
        raise ValueError(f"Le simulateur ne couvre pas le {day:%d/%m/%Y}.")
    files = [inbox / f"acd_{day:%Y%m%d}.csv", inbox / f"wfm_{day:%Y%m%d}.csv"]
    acd[acd["jour"] == day].drop(columns="jour").to_csv(files[0], index=False)
    wfm[wfm["jour"] == day].drop(columns="jour").to_csv(files[1], index=False)
    nxt = day + timedelta(days=1)
    plan = truth[pd.to_datetime(truth["ts"]).dt.date == nxt][["ts", "agents_scheduled"]]
    if len(plan):
        files.append(inbox / f"plan_{nxt:%Y%m%d}.csv")
        plan.to_csv(files[-1], index=False)
    return files


def current_plan_for(day: date, inbox: Path = INBOX_DIR, directory: Path = FUTURE_DIR) -> pd.Series:
    """Planning de l'outil WFM en place pour `day` (fichier deja depose, sinon monde futur)."""
    path = inbox / f"plan_{day:%Y%m%d}.csv"
    if path.exists():
        plan = pd.read_csv(path, parse_dates=["ts"])
    else:
        truth = load_future("truth", directory)
        plan = truth[pd.to_datetime(truth["ts"]).dt.date == day][["ts", "agents_scheduled"]]
    return plan.set_index("ts")["agents_scheduled"].astype(int)
