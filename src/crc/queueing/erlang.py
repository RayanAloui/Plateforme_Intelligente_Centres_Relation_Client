"""Modeles de files d'attente analytiques, vectorises sur des tableaux d'intervalles.

- Erlang C (M/M/n)   : sans abandon. Standard des planificateurs WFM.
- Erlang A (M/M/n+M) : avec abandon. Reste defini en surcharge (charge >= agents),
                       indispensable pendant les pics et les incidents.

Conventions : toutes les durees en secondes, lam en appels par seconde.
Ce module sert au generateur (Phase 1) et a l'optimiseur (Phase 4).
"""
import numpy as np


def erlang_c_wait_prob(n: np.ndarray, a: np.ndarray) -> np.ndarray:
    """Probabilite d'attente P(W > 0) de l'Erlang C. Vaut 1 si a >= n (instable)."""
    n = np.asarray(n, dtype=int)
    a = np.asarray(a, dtype=float)
    b = np.ones_like(a)                      # Erlang B par recurrence
    for k in range(1, int(n.max()) + 1):
        active = k <= n
        b = np.where(active, a * b / (k + a * b), b)
    with np.errstate(divide="ignore", invalid="ignore"):
        c = n * b / (n - a * (1 - b))
    return np.where(a < n, np.clip(c, 0, 1), 1.0)


def erlang_c_service_level(n, a, aht, target_seconds) -> np.ndarray:
    """Part des appels pris en charge en moins de target_seconds (Erlang C)."""
    n = np.asarray(n, dtype=float)
    a = np.asarray(a, dtype=float)
    pw = erlang_c_wait_prob(n, a)
    sl = 1 - pw * np.exp(-(n - a) * target_seconds / np.asarray(aht, dtype=float))
    return np.where(a < n, sl, 0.0)


def erlang_c_required_agents(a, aht, target_seconds, target_sl, n_max=500) -> np.ndarray:
    """Plus petit nombre d'agents atteignant le service level cible."""
    a = np.asarray(a, dtype=float)
    n = np.maximum(np.floor(a).astype(int) + 1, 1)
    for _ in range(n_max):
        ok = erlang_c_service_level(n, a, aht, target_seconds) >= target_sl
        if ok.all():
            break
        n = np.where(ok, n, n + 1)
    return n


def erlang_a_metrics(n, lam, aht, patience, target_seconds, extra_states=400, chunk=4000):
    """Indicateurs stationnaires de l'Erlang A par la chaine de naissance-mort.

    Retourne un dict : wait_prob, abandon_prob, asa (attente moyenne, s),
    service_level (part des appels servis en moins de target_seconds).

    wait_prob, abandon_prob et asa sont exacts (a la troncature pres). Le service
    level repose sur une approximation du temps passe en file, validee par
    simulation ; elle redonne exactement l'Erlang C quand la patience -> infini.
    """
    n = np.asarray(n, dtype=int)
    lam = np.asarray(lam, dtype=float)
    mu = 1 / np.asarray(aht, dtype=float)
    theta = 1 / np.asarray(patience, dtype=float) * np.ones_like(lam)

    out = {k: np.empty(len(n)) for k in ("wait_prob", "abandon_prob", "asa", "service_level")}
    k_max = int(n.max()) + extra_states
    ks = np.arange(k_max + 1)

    for s in range(0, len(n), chunk):
        sl_ = slice(s, s + chunk)
        nn, ll, mm, th = n[sl_, None], lam[sl_, None], mu[sl_, None], theta[sl_, None]
        # Taux de sortie de l'etat k : min(k,n) mu + max(k-n,0) theta
        death = np.minimum(ks[1:], nn) * mm + np.maximum(ks[1:] - nn, 0) * th
        log_pi = np.concatenate([np.zeros((len(ll), 1)),
                                 np.cumsum(np.log(ll) - np.log(death), axis=1)], axis=1)
        log_pi -= log_pi.max(axis=1, keepdims=True)
        pi = np.exp(log_pi)
        pi /= pi.sum(axis=1, keepdims=True)

        waiting = ks[None, :] >= nn
        queue = np.maximum(ks[None, :] - nn, 0)
        p_wait = (pi * waiting).sum(axis=1)
        eq = (pi * queue).sum(axis=1)
        l1, t1 = ll[:, 0], th[:, 0]
        p_ab = np.clip(t1 * eq / l1, 0, 1)
        asa = eq / l1
        # Un client qui attend reste en file en moyenne asa / p_wait secondes.
        # On approxime ce temps par une exponentielle : exact pour l'Erlang C,
        # legerement optimiste en forte surcharge (ecart mesure par simulation).
        with np.errstate(divide="ignore", invalid="ignore"):
            exit_rate = np.where(asa > 0, p_wait / asa, np.inf)
        quick_served = (p_wait - p_ab) * (1 - np.exp(-exit_rate * target_seconds))
        out["wait_prob"][sl_] = p_wait
        out["abandon_prob"][sl_] = p_ab
        out["asa"][sl_] = asa
        out["service_level"][sl_] = np.clip(1 - p_wait + quick_served, 0, 1)
    return out