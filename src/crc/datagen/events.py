"""Generation des evenements exceptionnels (table ref.events)."""
import numpy as np
import pandas as pd

from crc.datagen.params import EventParams


def _snap(ts: pd.Timestamp, minutes: int) -> pd.Timestamp:
    return ts.floor(f"{minutes}min")


def generate_events(
    start: pd.Timestamp,
    end: pd.Timestamp,
    params: EventParams,
    rng: np.random.Generator,
    granularity_minutes: int = 30,
) -> pd.DataFrame:
    """Evenements tires selon des processus de Poisson homogenes."""
    span = end - start
    months = span / pd.Timedelta(days=30.4375)
    years = span / pd.Timedelta(days=365.25)
    rows = []

    # Incidents techniques
    for _ in range(rng.poisson(params.incident_rate_per_month * months)):
        t0 = _snap(start + span * rng.uniform(), granularity_minutes)
        hours = np.clip(
            rng.lognormal(np.log(params.incident_duration_median_hours),
                          params.incident_duration_sigma),
            0.5, 12.0,
        )
        t1 = t0 + pd.Timedelta(minutes=granularity_minutes * max(1, round(hours * 2)))
        # Intensite de Pareto : 1 + echelle * X, X >= 1 a queue epaisse
        x = 1.0 + rng.pareto(params.incident_pareto_alpha)
        intensity = min(1.0 + params.incident_intensity_scale * x, params.incident_intensity_cap)
        rows.append((t0, t1, "incident_technique", round(intensity, 2),
                     f"Incident technique ({hours:.1f} h)"))

    # Campagnes commerciales
    for _ in range(rng.poisson(params.campaign_rate_per_year * years)):
        day = (start + span * rng.uniform()).normalize()
        t0 = day + pd.Timedelta(hours=8)
        n_days = int(rng.integers(params.campaign_min_days, params.campaign_max_days + 1))
        t1 = t0 + pd.Timedelta(days=n_days)
        intensity = rng.uniform(*params.campaign_intensity_range)
        rows.append((t0, t1, "campagne_commerciale", round(intensity, 2),
                     f"Campagne commerciale ({n_days} jours)"))

    df = pd.DataFrame(rows, columns=["start_ts", "end_ts", "event_type", "intensity", "description"])
    df["end_ts"] = df["end_ts"].clip(upper=end)
    return df.sort_values("start_ts").reset_index(drop=True)


def event_multiplier(ts: pd.Series, events: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Multiplicateur d'intensite et indicateur d'incident pour chaque intervalle.

    Les evenements qui se chevauchent se composent multiplicativement.
    """
    t = ts.to_numpy()
    mult = np.ones(len(t))
    incident = np.zeros(len(t), dtype=bool)
    for ev in events.itertuples():
        mask = (t >= np.datetime64(ev.start_ts)) & (t < np.datetime64(ev.end_ts))
        mult[mask] *= ev.intensity
        if ev.event_type == "incident_technique":
            incident |= mask
    return mult, incident