"""Catalogue des parametres : libelle, categorie, aide et bornes de validation.

La valeur vit en base (ref.cost_parameters) ; ce catalogue decrit comment la presenter
et la valider dans l'interface d'administration.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ParamSpec:
    label: str
    category: str
    help: str
    minimum: float
    maximum: float
    default: float
    unit: str


CATALOG: dict[str, ParamSpec] = {
    "cost_agent_hour": ParamSpec("Coût d'une heure d'agent", "Coûts", "Coût employeur chargé.", 5, 200, 28, "EUR/heure"),
    "cost_wait_second": ParamSpec("Coût d'une seconde d'attente", "Coûts", "Coût d'opportunité de l'attente client.", 0, 1, 0.005, "EUR/seconde"),
    "cost_abandoned_call": ParamSpec("Coût d'un appel abandonné", "Coûts", "Perte commerciale estimée par abandon.", 0, 500, 12, "EUR/appel"),
    "penalty_sla_breach": ParamSpec("Pénalité de non-respect du SLA", "Coûts", "Par demi-heure sous la cible.", 0, 5000, 50, "EUR/intervalle"),
    "sla_target_seconds": ParamSpec("Délai cible de réponse", "Service", "Seuil du service level (ex. 80/20).", 5, 120, 20, "secondes"),
    "sla_target_ratio": ParamSpec("Service level cible", "Service", "Part des appels pris en charge avant le délai cible.", 0.5, 0.99, 0.85, "ratio"),
    "risk_alpha": ParamSpec("Risque de sous-capacité toléré", "Risque et alertes", "Contrainte du planning recommandé.", 0.01, 0.5, 0.05, "probabilité"),
    "alert_medium_threshold": ParamSpec("Seuil d'alerte moyenne", "Risque et alertes", "Probabilité de sous-capacité déclenchant une surveillance.", 0.01, 0.9, 0.10, "probabilité"),
    "alert_high_threshold": ParamSpec("Seuil d'alerte élevée", "Risque et alertes", "Probabilité de sous-capacité déclenchant une intervention.", 0.02, 0.95, 0.20, "probabilité"),
    "agents_max_available": ParamSpec("Effectif maximal disponible", "Effectifs", "Agents mobilisables sur une demi-heure.", 1, 500, 60, "agents"),
    "shift_min_hours": ParamSpec("Durée minimale d'une vacation", "Vacations", "Plus courte vacation autorisée.", 2, 12, 4, "heures"),
    "max_shift_hours": ParamSpec("Durée maximale d'une vacation", "Vacations", "Plus longue vacation autorisée.", 4, 12, 8, "heures"),
    "shift_length_step_hours": ParamSpec("Pas des durées de vacation", "Vacations", "Ex. 2 : vacations de 4 h, 6 h, 8 h.", 1, 4, 2, "heures"),
}

CATEGORIES = ["Coûts", "Service", "Risque et alertes", "Effectifs", "Vacations"]


def seed_rows():
    """(nom, valeur, unite, source) pour l'initialisation de la base."""
    return [(name, spec.default, spec.unit, "Valeur initiale") for name, spec in CATALOG.items()]
