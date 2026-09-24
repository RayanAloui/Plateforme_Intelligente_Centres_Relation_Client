"""Niveau 1 du generateur : intensite d'arrivee et volumes d'appels.

Modele : processus de Cox (Poisson doublement stochastique).

    lambda_base(t) = niveau x tendance x saison x jour x intra-jour x calendrier
    lambda_vrai(t) = lambda_base(t) x evenements(t) x facteur_jour(d)
    offered(t)     ~ Poisson( lambda_vrai(t) x G(t) ),   G ~ Gamma(k, 1/k)

Le melange Gamma-Poisson produit une loi binomiale negative : la variance
depasse la moyenne, comme dans les donnees reelles de centres d'appels.
"""
import numpy as np
import pandas as pd

from crc.datagen.events import event_multiplier
from crc.datagen.params import DemandParams


def _normalize(x: np.ndarray) -> np.ndarray:
    return x / x.mean()


def intraday_profile(bumps, night_floor: float, periods_per_day: int) -> np.ndarray:
    """Profil sur une journee, normalise a une moyenne de 1."""
    step = 24 / periods_per_day
    hours = np.arange(periods_per_day) * step + step / 2   # centre de l'intervalle
    profile = np.full(periods_per_day, night_floor)
    for weight, peak, sd in bumps:
        profile += weight * np.exp(-0.5 * ((hours - peak) / sd) ** 2)
    return _normalize(profile)


def annual_profile(day_of_year: np.ndarray, monthly: tuple[float, ...]) -> np.ndarray:
    """Interpolation periodique entre les valeurs de mi-mois."""
    anchors = np.array([15.2 + 30.44 * m for m in range(12)])
    return np.interp(day_of_year, anchors, _normalize(np.array(monthly)), period=365.25)


def daily_factor(n_days: int, phi: float, sigma: float, rng: np.random.Generator) -> np.ndarray:
    """Facteur journalier log-AR(1), de moyenne 1.

    Il cree une correlation entre les intervalles d'une meme journee et entre
    jours consecutifs : c'est ce qui donne un vrai pouvoir predictif aux lags.
    """
    stationary_var = sigma**2 / (1 - phi**2)
    z = np.empty(n_days)
    z[0] = rng.normal(0, np.sqrt(stationary_var))
    for d in range(1, n_days):
        z[d] = phi * z[d - 1] + rng.normal(0, sigma)
    return np.exp(z - stationary_var / 2)


def base_intensity(calendar: pd.DataFrame, p: DemandParams, periods_per_day: int) -> np.ndarray:
    """Intensite deterministe : ce qu'un planificateur peut anticiper."""
    ts = calendar["ts"]
    years = ((ts - ts.iloc[0]).dt.total_seconds() / (365.25 * 86400)).to_numpy()

    trend = (1 + p.annual_growth) ** years
    season = annual_profile(ts.dt.dayofyear.to_numpy(), p.monthly_profile)
    weekday = _normalize(np.array(p.weekday_profile))[calendar["day_of_week"].to_numpy()]

    prof_week = intraday_profile(p.weekday_bumps, p.night_floor, periods_per_day)
    prof_wend = intraday_profile(p.weekend_bumps, p.night_floor, periods_per_day)
    idx = calendar["period_index"].to_numpy()
    use_weekend_shape = (calendar["is_weekend"] | calendar["is_holiday"]).to_numpy()
    intraday = np.where(use_weekend_shape, prof_wend[idx], prof_week[idx])

    holiday = np.where(calendar["is_holiday"], p.holiday_factor, 1.0)
    school = np.where(calendar["is_school_holiday"], p.school_holiday_factor, 1.0)

    # Lendemain de ferie (hors ferie consecutif)
    day_holiday = calendar.groupby("date")["is_holiday"].first()
    after = day_holiday.shift(1, fill_value=False) & ~day_holiday
    post = np.where(calendar["date"].map(after), p.post_holiday_factor, 1.0)

    return (p.mean_calls_per_interval * trend * season * weekday
            * intraday * holiday * school * post)


def generate_demand(
    calendar: pd.DataFrame,
    events: pd.DataFrame,
    p: DemandParams,
    rngs: dict[str, np.random.Generator],
    periods_per_day: int = 48,
) -> pd.DataFrame:
    """Volumes offerts et AHT cible par intervalle, avec la verite terrain."""
    lam_base = base_intensity(calendar, p, periods_per_day)
    ev_mult, is_incident = event_multiplier(calendar["ts"], events)

    day_codes, _ = pd.factorize(calendar["date"])
    day_f = daily_factor(day_codes.max() + 1, p.day_factor_phi, p.day_factor_sigma,
                         rngs["days"])[day_codes]

    lam_true = lam_base * ev_mult * day_f
    k = p.interval_gamma_shape
    offered = rngs["arrivals"].poisson(lam_true * rngs["arrivals"].gamma(k, 1 / k, len(lam_true)))

    # AHT cible (moyenne des durees de traitement sur l'intervalle)
    ts = calendar["ts"]
    years = ((ts - ts.iloc[0]).dt.total_seconds() / (365.25 * 86400)).to_numpy()
    hour = calendar["hour"].to_numpy()
    night = (hour < 7) | (hour >= 22)
    s = p.aht_noise_sigma
    aht_expected = (p.aht_base_seconds
                    * (1 + p.aht_annual_trend) ** years
                    * np.where(night, p.aht_night_factor, 1.0)
                    * np.where(calendar["is_weekend"], p.aht_weekend_factor, 1.0))
    aht = (aht_expected
           * np.where(is_incident, p.aht_incident_factor, 1.0)
           * rngs["aht"].lognormal(-s**2 / 2, s, len(ts)))

    return pd.DataFrame({
        "ts": ts.to_numpy(),
        "lambda_base": lam_base,
        "event_multiplier": ev_mult,
        "day_factor": day_f,
        "lambda_true": lam_true,
        "is_incident": is_incident,
        "offered": offered.astype(int),
        "aht_expected": aht_expected,
        "aht_seconds": aht,
    })