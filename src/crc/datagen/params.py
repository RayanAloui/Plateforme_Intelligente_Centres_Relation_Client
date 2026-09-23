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
class GeneratorParams:
    demand: DemandParams = field(default_factory=DemandParams)
    events: EventParams = field(default_factory=EventParams)