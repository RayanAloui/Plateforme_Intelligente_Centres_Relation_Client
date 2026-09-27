"""Variables explicatives pour la prevision a J+1.

Regle du jeu : la prevision du jour D est emise le soir de D-1. Elle ne peut
utiliser que des donnees anterieures a D 00:00. Consequence : le plus petit
retard autorise est 48 intervalles (meme demi-heure, la veille). Tout retard
plus court serait une fuite de donnees.
"""
import numpy as np
import pandas as pd

MIN_LAG = 48                                   # 1 jour = 48 demi-heures
LAGS = {"lag_1d": 48, "lag_1w": 336, "lag_2w": 672, "lag_3w": 1008, "lag_4w": 1344}

FEATURES = [
    # calendrier (connu a l'avance)
    "period", "dow", "month", "is_weekend", "is_holiday", "is_school_holiday", "post_holiday",
    "period_sin", "period_cos", "doy_sin", "doy_cos", "trend",
    # evenements planifies (les campagnes sont connues, les incidents non)
    "campaign",
    # historique (retards >= 1 jour)
    *LAGS, "mean_4w", "lag_1w_holiday", "day_total_1d", "day_total_1w",
]


def campaign_flag(ts: pd.DatetimeIndex, events: pd.DataFrame) -> np.ndarray:
    """1 si une campagne commerciale planifiee couvre l'intervalle."""
    flag = np.zeros(len(ts), dtype=int)
    t = ts.to_numpy()
    for ev in events[events["event_type"] == "campagne_commerciale"].itertuples():
        flag[(t >= np.datetime64(ev.start_ts)) & (t < np.datetime64(ev.end_ts))] = 1
    return flag


def build_features(df: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """df : historique indexe par horodatage (sortie de load_history)."""
    y = df["offered"].astype(float)
    X = pd.DataFrame(index=df.index)

    # --- Calendrier -----------------------------------------------------------------------
    X["period"] = df["period_index"]
    X["dow"] = df["day_of_week"]
    X["month"] = df["month"]
    X["is_weekend"] = df["is_weekend"].astype(int)
    X["is_holiday"] = df["is_holiday"].astype(int)
    X["is_school_holiday"] = df["is_school_holiday"].astype(int)
    day_holiday = df.groupby("date")["is_holiday"].first()
    after = day_holiday.shift(1, fill_value=False) & ~day_holiday
    X["post_holiday"] = df["date"].map(after).astype(int)

    periods_per_day = int(df["period_index"].max()) + 1
    angle = 2 * np.pi * df["period_index"] / periods_per_day
    X["period_sin"], X["period_cos"] = np.sin(angle), np.cos(angle)
    doy = 2 * np.pi * df.index.dayofyear / 365.25
    X["doy_sin"], X["doy_cos"] = np.sin(doy), np.cos(doy)
    X["trend"] = (df.index - df.index[0]).days / 365.25

    X["campaign"] = campaign_flag(df.index, events)

    # --- Historique : uniquement des retards >= 1 jour --------------------------------------
    for name, k in LAGS.items():
        X[name] = y.shift(k)
    X["mean_4w"] = X[["lag_1w", "lag_2w", "lag_3w", "lag_4w"]].mean(axis=1)
    X["lag_1w_holiday"] = df["is_holiday"].shift(LAGS["lag_1w"]).astype(float)

    daily = y.groupby(df["date"]).sum()
    X["day_total_1d"] = df["date"].map(daily.shift(1))
    X["day_total_1w"] = df["date"].map(daily.shift(7))
    return X[FEATURES]