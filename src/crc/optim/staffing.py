"""Optimisation des effectifs (modules 14, 15 et 16).

Sans contraintes de vacations (shifts), le cout total d'une journee est une somme de couts
par demi-heure, et chaque demi-heure ne depend que de son propre effectif : le probleme se
decompose en 48 petits problemes independants. On peut alors trouver l'optimum EXACT en
evaluant, pour chaque demi-heure, une plage d'effectifs candidats ("courbes de cout").

  Strategie IA                : prevision ponctuelle + Erlang A, service level cible atteint
                                en moyenne (le meme raisonnement que le planificateur, mieux informe)
  Strategie IA + risque       : minimise  cout des agents + perte attendue (Monte Carlo)
                                sous contraintes  SL moyen >= 85 %  et  P(sous-capacite) <= alpha
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from crc.queueing.erlang import erlang_a_metrics
from crc.risk.costs import INTERVAL_SECONDS, queue_losses
from crc.risk.simulation import OperationalRiskModel

OFFSETS = np.arange(-3, 9)          # effectifs candidats autour du plan deterministe


def staff_cost(n, costs: dict) -> np.ndarray:
    return costs["cost_agent_hour"] * INTERVAL_SECONDS / 3600 * np.asarray(n)


def deterministic_plan(mu: pd.Series, aht: pd.Series, absence_mean: float, patience: float,
                       costs: dict, n_min: int = 2) -> np.ndarray:
    """Strategie IA : plus petit effectif present atteignant la cible de SL pour le volume
    PREVU (sans incertitude), majore du taux d'absence moyen."""
    n_max = int(costs["agents_max_available"])
    present = np.full(len(mu), n_min)
    lam = np.maximum(mu.to_numpy(), 0.1) / INTERVAL_SECONDS
    todo = np.ones(len(mu), dtype=bool)
    while todo.any() and present.max() < n_max:
        m = erlang_a_metrics(present[todo], lam[todo], aht.to_numpy()[todo], patience,
                             costs["sla_target_seconds"])
        ok = m["service_level"] >= costs["sla_target_ratio"]
        idx = np.flatnonzero(todo)
        todo[idx[ok]] = False
        present[idx[~ok]] += 1
    return np.clip(np.ceil(present / (1 - absence_mean)).astype(int), n_min, n_max)


@dataclass
class StaffingCurves:
    """Pour chaque demi-heure (lignes) et chaque effectif candidat (colonnes)."""
    n: np.ndarray            # effectif planifie
    staff: np.ndarray        # cout des agents (EUR)
    loss: np.ndarray         # perte operationnelle attendue (EUR)
    sl: np.ndarray           # service level attendu
    undercap: np.ndarray     # probabilite de sous-capacite
    index: pd.DatetimeIndex


def build_curves(model: OperationalRiskModel, mu: pd.Series, aht: pd.Series, center: np.ndarray,
                 n_scenarios: int = 100, seed: int = 0, offsets: np.ndarray = OFFSETS) -> StaffingCurves:
    """Evalue chaque effectif candidat sur les MEMES scenarios (nombres aleatoires communs),
    pour que les differences entre candidats ne viennent pas du hasard du tirage."""
    rng = np.random.default_rng(seed)
    costs, n_max = model.costs, int(model.costs["agents_max_available"])
    dates = pd.Series(mu.index.date, index=mu.index)
    codes, uniques = pd.factorize(dates)
    arrivals = model.predictive.sample(mu, dates, n_scenarios, rng)                       # S x T
    absence = rng.choice(model.absence_rates, size=(n_scenarios, len(uniques)))[:, codes]  # S x T
    s = model.aht_sigma
    aht_s = aht.to_numpy()[None, :] * rng.lognormal(-s ** 2 / 2, s, size=arrivals.shape)

    n = np.clip(center[:, None] + offsets[None, :], 1, n_max)                              # T x K
    shape = (len(mu), len(offsets))
    loss, sl, under = np.empty(shape), np.empty(shape), np.empty(shape)
    for k in range(len(offsets)):
        present = np.maximum(np.round(n[None, :, k] * (1 - absence)), 1)
        q = queue_losses(arrivals, present, aht_s, model.patience, costs)
        w = arrivals + 1e-9
        loss[:, k] = q["perte"].mean(axis=0)
        sl[:, k] = (q["service_level"] * w).sum(axis=0) / w.sum(axis=0)
        under[:, k] = q["sous_capacite"].mean(axis=0)
    return StaffingCurves(n, staff_cost(n, costs), loss, sl, under, mu.index)


def risk_aware_plan(curves: StaffingCurves, costs: dict, alpha: float = 0.10) -> np.ndarray:
    """Strategie IA + risque : cout total minimal parmi les effectifs qui respectent
    SL attendu >= cible et P(sous-capacite) <= alpha (le plus grand candidat sinon)."""
    total = curves.staff + curves.loss
    feasible = (curves.sl >= costs["sla_target_ratio"]) & (curves.undercap <= alpha)
    total = np.where(feasible, total, np.inf)
    best = np.where(np.isfinite(total).any(axis=1), total.argmin(axis=1), curves.n.shape[1] - 1)
    return curves.n[np.arange(len(best)), best]


def budget_plan(curves: StaffingCurves, budget: float) -> np.ndarray:
    """What-if 'je veux reduire mon cout' : sous une enveloppe d'agents imposee, retire les agents
    la ou ils evitent le moins de pertes par euro (methode marginale gloutonne, optimale ici
    car la perte attendue est decroissante et convexe en l'effectif)."""
    k = np.full(curves.n.shape[0], curves.n.shape[1] - 1)
    rows = np.arange(len(k))
    while curves.staff[rows, k].sum() > budget and (k > 0).any():
        extra_loss = np.where(k > 0, curves.loss[rows, k - 1] - curves.loss[rows, k], np.inf)
        saving = np.where(k > 0, curves.staff[rows, k] - curves.staff[rows, k - 1], 1)
        t = int(np.argmin(extra_loss / np.maximum(saving, 1e-9)))
        k[t] -= 1
    return curves.n[rows, k]


def evaluate_plan(plan, offered: pd.Series, aht: pd.Series, absence_rate: pd.Series,
                  patience: float, costs: dict) -> pd.DataFrame:
    """Ce qui se serait passe avec ce planning face a la demande REELLE (contrefactuel).
    Le meme moteur Erlang A sert pour toutes les strategies : la comparaison est equitable."""
    present = np.maximum(np.round(np.asarray(plan) * (1 - absence_rate.to_numpy())), 1)
    q = queue_losses(offered.to_numpy()[None, :], present[None, :], aht.to_numpy()[None, :], patience, costs)
    m = erlang_a_metrics(present.astype(int), np.maximum(offered.to_numpy(), 0.1) / INTERVAL_SECONDS,
                         aht.to_numpy(), patience, costs["sla_target_seconds"])
    return pd.DataFrame({
        "agents_planifies": np.asarray(plan), "agents_presents": present, "appels": offered.to_numpy(),
        "cout_agents": staff_cost(plan, costs), "perte": q["perte"][0],
        "abandons": m["abandon_prob"] * offered.to_numpy(), "sl": q["service_level"][0],
        "sous_capacite": q["sous_capacite"][0],
    }, index=offered.index)