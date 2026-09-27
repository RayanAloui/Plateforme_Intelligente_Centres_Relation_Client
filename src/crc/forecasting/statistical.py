"""Modele statistique "top-down" : SARIMAX journalier + profil intra-journalier.

Pourquoi deux etages ? Un SARIMA directement a la demi-heure devrait gerer une
saisonnalite de 336 pas (une semaine), ce qui est tres lent et instable. La
pratique du workforce management est de separer :
  1. combien d'appels dans la journee    -> SARIMAX sur le total journalier
  2. comment ils se repartissent          -> profil moyen des 12 memes jours precedents

Le SARIMAX est separe en deux temps, pour pouvoir etre sauvegarde puis reutilise :
  fit_daily_model    : estime les parametres (une fois, sur l'entrainement)
  filter_daily_model : deroule le filtre de Kalman avec ces parametres figes
"""
import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX

from crc.forecasting.features import campaign_flag

ORDER = (1, 0, 1)
SEASONAL_ORDER = (1, 1, 1, 7)                  # saisonnalite hebdomadaire
SPEC = dict(order=ORDER, seasonal_order=SEASONAL_ORDER, trend="c",
            enforce_stationarity=False, enforce_invertibility=False)
EXOG = ["is_holiday", "post_holiday", "is_school_holiday", "campaign", "doy_sin", "doy_cos"]
PROFILE_WEEKS = 12                             # regle sur la validation (4 -> 16,4 %, 12 -> 15,5 %)


def daily_frame(df: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par jour : volume total et variables connues a l'avance.

    Un jour futur (volumes inconnus, NaN) garde un total NaN : le filtre de Kalman
    le traite comme une observation manquante et en produit la prevision.
    """
    d = pd.DataFrame({
        "total": df["offered"].groupby(df["date"]).sum(min_count=1).astype(float),
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


def fit_daily_model(daily: pd.DataFrame, train_end: pd.Timestamp) -> pd.Series:
    """Parametres du SARIMAX estimes sur les jours anterieurs a train_end."""
    train = daily.index < train_end
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fitted = SARIMAX(np.log(daily.loc[train, "total"]), exog=daily.loc[train, EXOG].astype(float),
                         **SPEC).fit(disp=False, maxiter=200)
    return fitted.params


def filter_daily_model(daily: pd.DataFrame, params: pd.Series) -> pd.Series:
    """Prevision a un pas (J+1) de chaque jour, avec des parametres figes.

    La prevision du jour D n'utilise que les observations jusqu'a D-1
    (plus le calendrier de D, connu a l'avance).
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = SARIMAX(np.log(daily["total"]), exog=daily[EXOG].astype(float), **SPEC).filter(params)
    return np.exp(res.get_prediction().predicted_mean)


def daily_forecast(daily: pd.DataFrame, train_end: pd.Timestamp) -> pd.Series:
    return filter_daily_model(daily, fit_daily_model(daily, train_end))


def daily_level(df: pd.DataFrame, events: pd.DataFrame, train_end: pd.Timestamp | None = None,
                params: pd.Series | None = None) -> pd.Series:
    """Niveau prevu du jour, ramene a la demi-heure (total prevu / nombre d'intervalles).

    Fournir soit train_end (estimation des parametres), soit params (parametres deja estimes).
    """
    daily = daily_frame(df, events)
    if params is None:
        params = fit_daily_model(daily, train_end)
    totals = filter_daily_model(daily, params)
    periods_per_day = int(df["period_index"].max()) + 1
    return pd.Series(totals.reindex(pd.to_datetime(df["date"])).to_numpy() / periods_per_day,
                     index=df.index, name="daily_level")


def intraday_profile(df: pd.DataFrame) -> pd.DataFrame:
    """Part de chaque demi-heure dans la journee, estimee sur les memes jours precedents.

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