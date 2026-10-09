"""Construction des vacations par programmation lineaire en nombres entiers (module 14).

Le planning recommande donne un BESOIN par demi-heure. On ne peut pas faire venir un agent
pour trente minutes : il faut des vacations continues, de duree autorisee (4 h, 6 h, 8 h).

Variables      x[s, d]  nombre d'agents commencant a la demi-heure s pour une duree d
Couverture     c_t = somme des x[s, d] dont la vacation couvre t
Contraintes    c_t >= minimum_t     (risque de sous-capacite <= alpha, SL attendu >= cible)
               c_t <= effectif maximal disponible
Objectif       cout des heures payees + cout fixe par vacation + perte attendue(c_t)

La perte attendue en fonction de la couverture vient des courbes Monte Carlo de l'etape 4
(build_curves). Elle est decroissante et convexe : on la represente exactement par son
enveloppe convexe inferieure (une contrainte par segment), ce qui garde un modele lineaire.
Le modele arbitre donc lui-meme : ajouter un agent sur une vacation entiere vaut-il la perte
qu'il evite sur chacune des demi-heures couvertes ?

Hypothese : journee cyclique (service 24h/24). Une vacation de nuit qui commence a 22h couvre
aussi le debut de la journee ; en pratique, c'est la vacation de nuit de la veille qui l'assure.
Resolution : solveur CP-SAT d'OR-Tools, montants en centimes (coefficients entiers).
Regles de lisibilite : vacations commencant a l'heure pile, cout fixe par agent et par vacation,
et cout par type de vacation utilise (un planning a 12 types est plus simple qu'a 35).
"""
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
from ortools.sat.python import cp_model

from crc.optim.staffing import StaffingCurves

FIXED_COST_PER_SHIFT = 5.0        # EUR par agent et par vacation (trajet, prise de poste)
PATTERN_COST = 30.0               # EUR par type de vacation utilise : un planning lisible, peu fragmente
START_STEP_PERIODS = 2            # les vacations commencent a l'heure pile
DETERMINISTIC_TIME = 5.0          # budget de calcul en "temps deterministe" : resultat reproductible
TIME_LIMIT_SECONDS = 30.0         # garde-fou en temps reel


@dataclass
class ShiftSolution:
    shifts: pd.DataFrame          # debut, fin, duree_h, agents
    coverage: np.ndarray          # agents presents par demi-heure (planifies)
    minimum: np.ndarray           # couverture minimale imposee par le risque
    status: str                   # OPTIMAL (prouve) ou FEASIBLE (meilleure solution trouvee dans le temps imparti)
    gap: float                    # ecart relatif maximal a l'optimum (0 si prouve)
    paid_hours: float
    staff_cost: float
    expected_loss: float          # perte attendue selon les courbes
    solve_seconds: float


def shift_lengths(costs: dict) -> list[int]:
    """Durees autorisees en heures, d'apres les parametres (ex. 4, 6, 8)."""
    lo, hi = int(costs.get("shift_min_hours", 4)), int(costs.get("max_shift_hours", 8))
    step = max(1, int(costs.get("shift_length_step_hours", 2)))
    return list(range(lo, hi + 1, step))


def minimum_coverage(curves: StaffingCurves, costs: dict, alpha: float) -> np.ndarray:
    """Plus petit effectif candidat qui respecte le risque tolere et la cible de service level."""
    ok = (curves.undercap <= alpha) & (curves.sl >= costs["sla_target_ratio"])
    first = np.where(ok.any(axis=1), ok.argmax(axis=1), curves.n.shape[1] - 1)
    return curves.n[np.arange(len(first)), first]


def lower_hull(xs: np.ndarray, ys: np.ndarray) -> list[tuple[int, int]]:
    """Enveloppe convexe inferieure de points (x croissants) : chaine monotone d'Andrew."""
    pts = sorted({int(x): int(y) for x, y in zip(xs, ys)}.items())
    hull: list[tuple[int, int]] = []
    for p in pts:
        while len(hull) >= 2:
            (x1, y1), (x2, y2) = hull[-2], hull[-1]
            if (x2 - x1) * (p[1] - y1) - (y2 - y1) * (p[0] - x1) <= 0:
                hull.pop()
            else:
                break
        hull.append(p)
    return hull


def schedule_shifts(curves: StaffingCurves, costs: dict, alpha: float,
                    time_limit: float = TIME_LIMIT_SECONDS, lengths: list[int] | None = None,
                    start_step: int = START_STEP_PERIODS, pattern_cost: float = PATTERN_COST) -> ShiftSolution:
    """Vacations optimales. Les regles (durees, pas de debut, cout par type) sont modifiables
    pour mesurer le "prix de la rigidite" d'une organisation du travail."""
    started = time.perf_counter()
    T = curves.n.shape[0]
    max_agents = int(costs["agents_max_available"])
    per_period = int(round(100 * costs["cost_agent_hour"] / 2))          # centimes par demi-heure
    fixed = int(round(100 * FIXED_COST_PER_SHIFT))
    minimum = np.minimum(minimum_coverage(curves, costs, alpha), max_agents)

    model = cp_model.CpModel()
    templates = [(s, 2 * h) for h in (lengths or shift_lengths(costs)) for s in range(0, T, start_step)]
    x = {(s, d): model.NewIntVar(0, max_agents, f"x_{s}_{d}") for s, d in templates}
    used = {key: model.NewBoolVar(f"u_{key[0]}_{key[1]}") for key in templates}
    for key, var in x.items():
        model.Add(var <= max_agents * used[key])          # un type de vacation n'est utilise que si choisi
    cover = [[] for _ in range(T)]
    for (s, d), var in x.items():
        for k in range(d):
            cover[(s + k) % T].append(var)

    losses = []
    for t in range(T):
        c = model.NewIntVar(int(minimum[t]), max_agents, f"c_{t}")
        model.Add(c == sum(cover[t]))
        loss_cents = np.round(100 * curves.loss[t]).astype(int)
        hull = lower_hull(curves.n[t], loss_cents)
        L = model.NewIntVar(0, int(loss_cents.max()) + 1, f"L_{t}")
        for (x1, y1), (x2, y2) in zip(hull, hull[1:]):
            # (x2 - x1) * L >= (x2 - x1) * y1 + (y2 - y1) * (c - x1)
            model.Add((x2 - x1) * L >= (x2 - x1) * y1 + (y2 - y1) * (c - x1))
        model.Add(L >= hull[-1][1])                     # au-dela des candidats : perte residuelle
        losses.append(L)

    pattern = int(round(100 * pattern_cost))
    model.Minimize(sum(per_period * d * v + fixed * v for (s, d), v in x.items())
                   + pattern * sum(used.values()) + sum(losses))
    solver = cp_model.CpSolver()
    # Recherche entrelacee + budget deterministe : la meme journee donne toujours les memes vacations.
    solver.parameters.num_workers = 8
    solver.parameters.interleave_search = True
    solver.parameters.max_deterministic_time = DETERMINISTIC_TIME
    solver.parameters.max_time_in_seconds = time_limit
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("Aucune combinaison de vacations ne respecte les contraintes.")

    rows = [(s, d, solver.Value(v)) for (s, d), v in x.items() if solver.Value(v) > 0]
    coverage = np.zeros(T, dtype=int)
    for s, d, n in rows:
        for k in range(d):
            coverage[(s + k) % T] += n
    shifts = pd.DataFrame(rows, columns=["debut_periode", "duree_periodes", "agents"])
    paid_hours = float((shifts["duree_periodes"] * shifts["agents"]).sum() / 2) if len(shifts) else 0.0
    return ShiftSolution(
        shifts=shifts, coverage=coverage, minimum=minimum,
        status="OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE",
        gap=0.0 if status == cp_model.OPTIMAL else
            max(0.0, (solver.ObjectiveValue() - solver.BestObjectiveBound()) / max(solver.ObjectiveValue(), 1)),
        paid_hours=paid_hours, staff_cost=paid_hours * costs["cost_agent_hour"],
        expected_loss=sum(solver.Value(L) for L in losses) / 100,
        solve_seconds=round(time.perf_counter() - started, 2),
    )


def shifts_frame(solution: ShiftSolution, day_start: pd.Timestamp) -> pd.DataFrame:
    """Vacations avec dates et heures reelles (une vacation de nuit peut finir le lendemain)."""
    s = solution.shifts
    start = day_start + pd.to_timedelta(s["debut_periode"] * 30, unit="min")
    return pd.DataFrame({"debut": start, "fin": start + pd.to_timedelta(s["duree_periodes"] * 30, unit="min"),
                         "duree_h": s["duree_periodes"] / 2, "agents": s["agents"]}).sort_values(["debut", "fin"])
