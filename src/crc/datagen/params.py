"""Parametres du generateur de demande.

Tous les choix de modelisation sont regroupes ici : ce fichier est la
reference a citer dans le memoire pour decrire le generateur.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DemandParams:
    # --- Niveau et tendance -------------------------------------------------
    mean_calls_per_interval: float = 75.0   # niveau moyen en debut d'historique
    annual_growth: float = 0.07             # croissance annuelle de l'activite

    # --- Saisonnalite annuelle (valeur au 15 de chaque mois, jan -> dec) -----
    monthly_profile: tuple[float, ...] = (
        1.12, 1.02, 1.00, 0.97, 0.93, 0.95, 0.88, 0.78, 1.10, 1.05, 1.03, 0.95,
    )

    # --- Effet jour de semaine (lundi -> dimanche) ---------------------------
    weekday_profile: tuple[float, ...] = (1.18, 1.08, 1.02, 1.00, 0.95, 0.62, 0.48)

    # --- Profil intra-journalier : somme de bosses gaussiennes ----------------
    # (poids, heure du pic, ecart-type en heures)
    weekday_bumps: tuple[tuple[float, float, float], ...] = (
        (1.00, 10.5, 1.6), (0.85, 14.8, 1.9), (0.25, 19.0, 1.5),
    )
    weekend_bumps: tuple[tuple[float, float, float], ...] = (
        (0.80, 11.5, 2.2), (0.60, 16.0, 2.5),
    )
    night_floor: float = 0.10               # activite residuelle (service 24/7)

    # --- Effets calendaires ---------------------------------------------------
    holiday_factor: float = 0.45
    post_holiday_factor: float = 1.12        # rattrapage le lendemain d'un ferie
    school_holiday_factor: float = 0.94

    # --- Stochasticite (processus de Cox) --------------------------------------
    day_factor_phi: float = 0.60             # persistance AR(1) du facteur journalier
    day_factor_sigma: float = 0.05           # volatilite du facteur journalier (log)
    interval_gamma_shape: float = 60.0       # surdispersion intra-journaliere

    # --- Temps de traitement (AHT) -------------------------------------------
    aht_base_seconds: float = 300.0
    aht_annual_trend: float = -0.015         # effet d'apprentissage
    aht_night_factor: float = 1.12
    aht_weekend_factor: float = 1.05
    aht_incident_factor: float = 1.10
    aht_noise_sigma: float = 0.06


@dataclass(frozen=True)
class EventParams:
    # Incidents techniques : frequents, courts, intensite a queue epaisse
    incident_rate_per_month: float = 1.2
    incident_duration_median_hours: float = 3.0
    incident_duration_sigma: float = 0.6
    incident_pareto_alpha: float = 3.0
    incident_intensity_scale: float = 0.5
    incident_intensity_cap: float = 5.0

    # Campagnes commerciales : rares, longues, effet modere
    campaign_rate_per_year: float = 4.0
    campaign_min_days: int = 3
    campaign_max_days: int = 10
    campaign_intensity_range: tuple[float, float] = (1.10, 1.30)


@dataclass(frozen=True)
class OperationsParams:
    # --- Planificateur (strategie "baseline") ----------------------------------
    planning_error_sigma: float = 0.05       # erreur journaliere de prevision (log)
    planner_target_sl: float = 0.80          # standard 80/20 du secteur
    sla_target_seconds: float = 20.0
    planner_shrinkage: float = 0.06          # marge prevue pour les absences
    min_agents: int = 2
    max_agents: int = 60                     # coherent avec ref.cost_parameters

    # --- Absences ----------------------------------------------------------------
    absence_by_season: tuple[tuple[str, float], ...] = (
        ("Hiver", 0.080), ("Printemps", 0.060), ("Ete", 0.045), ("Automne", 0.065),
    )
    absence_day_sigma: float = 0.25          # variabilite journaliere (log)
    exceptional_absence_rate_per_year: float = 3.0
    exceptional_absence_extra: tuple[float, float] = (0.15, 0.30)

    # --- Comportement client -------------------------------------------------------
    patience_mean_seconds: float = 180.0
    wait_noise_sigma: float = 0.15

    # --- Satisfaction -------------------------------------------------------------------
    csat_base: float = 4.4
    csat_wait_coef: float = 0.006            # points perdus par seconde d'attente
    csat_abandon_coef: float = 1.5
    csat_noise_sd: float = 0.3
    csat_response_rate: float = 0.08


@dataclass(frozen=True)
class GeneratorParams:
    demand: DemandParams = field(default_factory=DemandParams)
    events: EventParams = field(default_factory=EventParams)
    operations: OperationsParams = field(default_factory=OperationsParams)