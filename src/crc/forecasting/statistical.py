"""Modele statistique "top-down" : SARIMAX journalier + profil intra-journalier.

Pourquoi deux etages ? Un SARIMA directement a la demi-heure devrait gerer une
saisonnalite de 336 pas (une semaine), ce qui est tres lent et instable. La
pratique du workforce management est de separer :
  1. combien d'appels dans la journee    -> SARIMAX sur le total journalier
  2. comment ils se repartissent          -> profil moyen des 4 memes jours precedents
"""
import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX

from crc.forecasting.features import campaign_flag

ORDER = (1, 0, 1)
SEASONAL_ORDER = (1, 1, 1, 7)                  # saisonnalite hebdomadaire
EXOG = ["is_holiday", "post_holiday", "is_school_holiday", "campaign", "doy_sin", "doy_cos"]
PROFILE_WEEKS = 12


def daily_frame(df: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par jour : volume total et variables connues a l'avance."""
    d = pd.DataFrame({
        "total": df["offered"].groupby(df["date"]).sum().astype(float),
        "dow": df.groupby("date")["day_of_week"].first(),
        "is_holiday": df.groupby("date")["is_holiday"].first().astype(int),
        "is_school_holiday": df.groupby("date")["is_school_holiday"].first().astype(int),
        # part de la journee couverte par une campagne planifiee
        "campaign": pd.Series(campaign_flag(df.index, events), index=df.index)
                      .groupby(df["date"]).mean(),
    })
    d.index = pd.to_datetime(d.index)
    d["post_holiday"] = (d["is_holiday"].shift(1, fill_value=0).astype(bool)
                         & ~d["is_holiday"].astype(bool)).astype(int)
    angle = 2 * np.pi * d.index.dayofyear / 365.25
    d["doy_sin"], d["doy_cos"] = np.sin(angle), np.cos(angle)
    return d


def daily_forecast(daily: pd.DataFrame, train_end: pd.Timestamp) -> pd.Series:
    """Prevision a un pas (J+1) du total journalier pour toutes les dates.

    Les parametres sont estimes sur l'entrainement uniquement, puis le filtre
    de Kalman est deroule sur toute la serie : la prevision du jour D n'utilise
    que les observations jusqu'a D-1 (plus le calendrier de D, connu a l'avance).
    """
    y = np.log(daily["total"])
    X = daily[EXOG].astype(float)
    train = daily.index < train_end
    spec = dict(order=ORDER, seasonal_order=SEASONAL_ORDER, trend="c",
                enforce_stationarity=False, enforce_invertibility=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fitted = SARIMAX(y[train], exog=X[train], **spec).fit(disp=False, maxiter=200)
        full = SARIMAX(y, exog=X, **spec).filter(fitted.params)
    return np.exp(full.get_prediction().predicted_mean)


def intraday_profile(df: pd.DataFrame) -> pd.DataFrame:
    """Part de chaque demi-heure dans la journee, estimee sur les 4 memes jours precedents.

    Les jours feries sont regroupes avec les dimanches, dont ils partagent la forme.
    """
    total = df["offered"].groupby(df["date"]).transform("sum")
    shares = (df["offered"] / total.replace(0, np.nan)).fillna(0)
    S = shares.groupby([df["date"], df["period_index"]]).first().unstack()
    S.index = pd.to_datetime(S.index)
    day = df.groupby("date")[["day_of_week", "is_holiday"]].first()
    key = np.where(day["is_holiday"], 6, day["day_of_week"])
    profile = S.groupby(key).transform(
        lambda g: g.shift(1).rolling(PROFILE_WEEKS, min_periods=1).mean())
    return profile.div(profile.sum(axis=1), axis=0)

def daily_level(df: pd.DataFrame, events: pd.DataFrame, train_end: pd.Timestamp) -> pd.Series:
    """Niveau prevu du jour, ramene a la demi-heure (total prevu / nombre d'intervalles)."""
    totals = daily_forecast(daily_frame(df, events), train_end)
    periods_per_day = int(df["period_index"].max()) + 1
    return pd.Series(totals.reindex(pd.to_datetime(df["date"])).to_numpy() / periods_per_day,
                     index=df.index, name="daily_level")

def top_down_forecast(df: pd.DataFrame, events: pd.DataFrame, train_end: pd.Timestamp,
                      level: pd.Series | None = None) -> pd.Series:
    """Prevision a la demi-heure = niveau du jour prevu x profil prevu.

    level (optionnel) : niveau deja calcule par daily_level, pour eviter de reestimer le SARIMAX.
    """
    if level is None:
        level = daily_level(df, events, train_end)
    profile = intraday_profile(df)
    periods_per_day = profile.shape[1]
    dates = pd.to_datetime(df["date"])
    shares = profile.to_numpy()[profile.index.get_indexer(dates), df["period_index"].to_numpy()]
    return pd.Series(level.to_numpy() * periods_per_day * shares, index=df.index,
                     name="sarimax_top_down")