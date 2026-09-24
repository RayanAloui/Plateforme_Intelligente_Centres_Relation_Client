"""Niveau 2 du generateur : effectifs, absences et KPI.

Chaine causale, intervalle par intervalle :

    lambda_base --(erreur de prevision)--> prevision du planificateur
        --(Erlang C, cible 80/20, marge d'absence)--> agents planifies
        --(absences)--> agents presents
    volume reel + AHT reel + agents presents --(Erlang A)--> attente, abandons, SL
        --> occupation, satisfaction

Les KPI ne sont jamais tires independamment : ils decoulent du volume et des
effectifs, donc les relations entre variables sont coherentes par construction.
"""
import numpy as np
import pandas as pd

from crc.datagen.params import OperationsParams
from crc.queueing.erlang import erlang_a_metrics, erlang_c_required_agents


def plan_staffing(calendar, demand, p: OperationsParams, rng, interval_seconds):
    """Planning 'baseline' : Erlang C sur une prevision imparfaite."""
    day_codes, _ = pd.factorize(calendar["date"])
    error = np.exp(rng.normal(0, p.planning_error_sigma, day_codes.max() + 1))[day_codes]
    lam_plan = demand["lambda_base"].to_numpy() * error
    load_plan = lam_plan * demand["aht_expected"].to_numpy() / interval_seconds

    required = erlang_c_required_agents(load_plan, demand["aht_expected"].to_numpy(),
                                        p.sla_target_seconds, p.planner_target_sl)
    scheduled = np.ceil(required / (1 - p.planner_shrinkage)).astype(int)
    return np.clip(scheduled, p.min_agents, p.max_agents), lam_plan


def draw_absences(calendar, scheduled, p: OperationsParams, rng):
    """Taux d'absence journalier (saison + alea + jours exceptionnels)."""
    days = calendar.groupby("date", sort=True)["season"].first()
    base = days.map(dict(p.absence_by_season)).to_numpy()
    rate = base * rng.lognormal(-p.absence_day_sigma**2 / 2, p.absence_day_sigma, len(days))

    n_years = len(days) / 365.25
    n_exc = rng.poisson(p.exceptional_absence_rate_per_year * n_years)
    exc_days = rng.choice(len(days), size=n_exc, replace=False)
    rate[exc_days] += rng.uniform(*p.exceptional_absence_extra, n_exc)
    rate = np.clip(rate, 0, 0.6)

    day_codes = pd.Index(days.index).get_indexer(calendar["date"])
    day_rate = rate[day_codes]
    present = np.maximum(rng.binomial(scheduled, 1 - day_rate), 1)
    return present, day_rate


def simulate_operations(calendar, demand, p: OperationsParams, rngs, interval_seconds=1800):
    """Genere effectifs et KPI observes, plus la verite terrain associee."""
    scheduled, lam_plan = plan_staffing(calendar, demand, p, rngs["staffing"], interval_seconds)
    present, absence_rate = draw_absences(calendar, scheduled, p, rngs["absence"])
    present = np.minimum(present, scheduled)

    offered = demand["offered"].to_numpy()
    aht = demand["aht_seconds"].to_numpy()
    lam = np.maximum(offered, 0.1) / interval_seconds       # evite lam = 0
    m = erlang_a_metrics(present, lam, aht, p.patience_mean_seconds, p.sla_target_seconds)

    rq = rngs["queue"]
    abandoned = rq.binomial(offered, m["abandon_prob"])
    answered = offered - abandoned
    quick = np.minimum(rq.binomial(offered, m["service_level"]), answered)

    has_calls = offered > 0
    safe = np.where(has_calls, offered, 1)
    service_level = np.where(has_calls, quick / safe, 1.0)
    abandon_rate = np.where(has_calls, abandoned / safe, 0.0)
    s = p.wait_noise_sigma
    avg_wait = np.where(has_calls,
                        m["asa"] * rq.lognormal(-s**2 / 2, s, len(offered)), 0.0)
    occupancy = np.clip(answered * aht / (present * interval_seconds), 0, 1)

    rn = rngs["noise"]
    responses = rn.binomial(answered, p.csat_response_rate)
    csat_true = p.csat_base - p.csat_wait_coef * avg_wait - p.csat_abandon_coef * abandon_rate
    csat = csat_true + rn.normal(0, p.csat_noise_sd / np.sqrt(np.maximum(responses, 1)))
    csat = np.where(responses > 0, np.clip(csat, 1, 5), np.nan)

    return pd.DataFrame({
        "ts": demand["ts"].to_numpy(),
        "offered": offered,
        "answered": answered,
        "abandoned": abandoned,
        "avg_wait_seconds": avg_wait.round(2),
        "avg_handle_seconds": aht.round(2),
        "agents_scheduled": scheduled,
        "agents_present": present,
        "agents_absent": scheduled - present,
        "service_level": service_level.round(4),
        "abandon_rate": abandon_rate.round(4),
        "occupancy": occupancy.round(4),
        "csat_mean": np.round(csat, 3),
        "csat_responses": responses,
        # --- verite terrain (non observable) ---
        "truth_lambda_plan": lam_plan,
        "truth_absence_rate": absence_rate,
        "truth_expected_sl": m["service_level"],
    })