"""Traduction des KPI en euros : le pont entre l'operationnel et le financier.

Pour chaque demi-heure, la perte operationnelle est :
    attente   : cout_seconde_attente x attente moyenne x appels offerts
    abandons  : cout_appel_abandonne x appels abandonnes
    penalite  : penalite_SLA si le service level passe sous la cible
Le cout des agents est compte a part : c'est une depense choisie, pas une perte subie.
"""
import numpy as np
import pandas as pd

from crc.queueing.erlang import erlang_a_metrics

DEFAULT_COSTS = {
    "cost_agent_hour": 28.0, "cost_wait_second": 0.005, "cost_abandoned_call": 12.0,
    "sla_target_seconds": 20.0, "sla_target_ratio": 0.85, "penalty_sla_breach": 50.0,
    "max_shift_hours": 8.0, "agents_max_available": 60.0,
}
INTERVAL_SECONDS = 1800


def load_costs() -> dict:
    """Parametres economiques depuis ref.cost_parameters (valeurs par defaut si la base est absente)."""
    try:
        from crc.db import read_sql
        table = read_sql("SELECT param_name, value FROM ref.cost_parameters")
        return {**DEFAULT_COSTS, **dict(zip(table["param_name"], table["value"].astype(float)))}
    except Exception:
        return dict(DEFAULT_COSTS)


def observed_losses(df: pd.DataFrame, costs: dict) -> pd.DataFrame:
    """Pertes reellement subies, calculees a partir des KPI observes."""
    out = pd.DataFrame(index=df.index)
    out["attente"] = costs["cost_wait_second"] * df["avg_wait_seconds"] * df["offered"]
    out["abandons"] = costs["cost_abandoned_call"] * df["abandoned"]
    out["penalite"] = np.where((df["offered"] > 0) & (df["service_level"] < costs["sla_target_ratio"]),
                               costs["penalty_sla_breach"], 0.0)
    out["perte"] = out[["attente", "abandons", "penalite"]].sum(axis=1)
    out["cout_agents"] = costs["cost_agent_hour"] * INTERVAL_SECONDS / 3600 * df["agents_present"]
    return out


def queue_losses(arrivals, agents, aht, patience: float, costs: dict, rng=None) -> dict:
    """Pertes attendues d'apres l'Erlang A, pour des tableaux de meme forme (scenarios x intervalles).

    Avec rng, le service level est tire autour de sa valeur attendue (bruit binomial),
    comme le serait un service level reellement mesure.
    """
    shape = np.shape(arrivals)
    a = np.asarray(arrivals, dtype=float).ravel()
    n = np.maximum(np.asarray(agents).ravel(), 1).astype(int)
    m = erlang_a_metrics(n, np.maximum(a, 0.1) / INTERVAL_SECONDS, np.asarray(aht, dtype=float).ravel(),
                         patience, costs["sla_target_seconds"])
    sl = m["service_level"]
    if rng is not None:
        sl = np.where(a > 0, rng.binomial(a.astype(int), sl) / np.maximum(a, 1), 1.0)
    wait = costs["cost_wait_second"] * m["asa"] * a
    abandon = costs["cost_abandoned_call"] * m["abandon_prob"] * a
    penalty = np.where((a > 0) & (sl < costs["sla_target_ratio"]), costs["penalty_sla_breach"], 0.0)
    undercap = a * np.asarray(aht, dtype=float).ravel() / INTERVAL_SECONDS > n
    r = lambda x: x.reshape(shape)
    return {"perte": r(wait + abandon + penalty), "attente": r(wait), "abandons": r(abandon),
            "penalite": r(penalty), "service_level": r(sl), "sous_capacite": r(undercap)}


def estimate_patience(df: pd.DataFrame, grid=np.arange(60, 421, 20), sample: int = 6000, seed: int = 0) -> float:
    """Patience moyenne des clients, estimee sur l'historique : celle qui reproduit le mieux
    les abandons observes avec l'Erlang A (moindres carres sur un echantillon d'intervalles)."""
    d = df[(df["offered"] >= 20) & ~df["is_imputed"]].sample(min(sample, len(df)), random_state=seed)
    lam = d["offered"].to_numpy() / INTERVAL_SECONDS
    errors = []
    for p in grid:
        m = erlang_a_metrics(d["agents_present"].to_numpy(), lam, d["avg_handle_seconds"].to_numpy(), p, 20)
        errors.append(((m["abandon_prob"] * d["offered"] - d["abandoned"]) ** 2).sum())
    return float(grid[int(np.argmin(errors))])