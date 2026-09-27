"""Machine Learning pour la prevision : LightGBM direct et modele hybride.

Constat de l'etape 2.4 : un LightGBM applique directement aux volumes sous-estime
systematiquement la periode de validation (biais d'environ -5 %). Les arbres de
decision ne savent pas extrapoler : ils n'ont jamais vu de volumes aussi eleves
qu'en 2024, puisque l'activite croit de 7 % par an.

Solution hybride : le SARIMAX (qui gere la tendance) fournit le niveau du jour,
LightGBM apprend seulement la FORME de la journee et les ecarts a ce niveau.
Techniquement : perte de Poisson avec un offset log(niveau), comme dans un GLM.
"""
import lightgbm as lgb
import numpy as np
import pandas as pd

from crc.forecasting.features import FEATURES
from crc.forecasting.statistical import daily_level

CATEGORICAL = ["period", "dow", "month"]
# Les premieres semaines, le filtre SARIMAX et les retards ne sont pas encore
# stabilises (il faut au moins une saison complete) : on les exclut de l'apprentissage.
WARMUP = pd.Timedelta(days=28)
PARAMS = dict(objective="poisson", n_estimators=300, learning_rate=0.05, num_leaves=31,
              min_child_samples=40, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
              random_state=0, verbose=-1)

# Le modele hybride n'a besoin que du calendrier : le niveau vient du SARIMAX.
SHAPE_FEATURES = ["period", "dow", "month", "is_weekend", "is_holiday", "is_school_holiday",
                  "post_holiday", "period_sin", "period_cos", "doy_sin", "doy_cos", "campaign"]


def _train_mask(df: pd.DataFrame, X: pd.DataFrame, cols: list, train_end: pd.Timestamp) -> np.ndarray:
    """Entrainement : apres le rodage, avant train_end, hors valeurs reconstituees."""
    return ((df.index >= df.index[0] + WARMUP) & (df.index < train_end)
            & ~df["is_imputed"].to_numpy()
            & X[cols].notna().all(axis=1).to_numpy())


def lightgbm_direct(df: pd.DataFrame, X: pd.DataFrame, train_end: pd.Timestamp) -> pd.Series:
    """LightGBM sur toutes les variables et la cible brute (conserve comme point de comparaison)."""
    mask = _train_mask(df, X, FEATURES, train_end)
    model = lgb.LGBMRegressor(**PARAMS).fit(
        X.loc[mask, FEATURES], df.loc[mask, "offered"], categorical_feature=CATEGORICAL)
    return pd.Series(model.predict(X[FEATURES]), index=X.index, name="lightgbm_direct")


class HybridForecaster:
    """Niveau du jour par SARIMAX x forme de la journee par LightGBM."""

    def fit(self, df: pd.DataFrame, X: pd.DataFrame, events: pd.DataFrame, train_end: pd.Timestamp):
        self.level = daily_level(df, events, train_end)
        offset = np.log(self.level.clip(lower=0.5))
        mask = _train_mask(df, X, SHAPE_FEATURES, train_end)
        self.model = lgb.LGBMRegressor(**PARAMS).fit(
            X.loc[mask, SHAPE_FEATURES], df.loc[mask, "offered"],
            init_score=offset[mask], categorical_feature=CATEGORICAL)
        return self

    def predict(self, X: pd.DataFrame) -> pd.Series:
        offset = np.log(self.level.reindex(X.index).clip(lower=0.5))
        raw = self.model.predict(X[SHAPE_FEATURES], raw_score=True)
        return pd.Series(np.exp(raw + offset), index=X.index, name="hybride")