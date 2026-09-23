"""Flux aleatoires independants, derives d'une seule graine."""
import numpy as np

STREAMS = ("events", "days", "arrivals", "aht", "staffing", "absence", "queue", "noise")


def make_rngs(seed: int) -> dict[str, np.random.Generator]:
    """Un generateur par composante.

    Modifier une composante (ex. la loi des absences) ne decale pas les tirages
    des autres : les volumes restent identiques d'une version a l'autre.
    """
    children = np.random.SeedSequence(seed).spawn(len(STREAMS))
    return {name: np.random.default_rng(c) for name, c in zip(STREAMS, children)}