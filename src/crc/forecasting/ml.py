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
from crc.forecasting.statistical import daily_frame, daily_level, fit_daily_model

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
    """Niveau du jour par SARIMAX x forme de la journee par LightGBM.

    Apres fit, le modele contient tout ce qu'il faut pour prevoir de nouvelles
    journees : les parametres du SARIMAX (sarimax_params) et le LightGBM (model).
    """

    def fit(self, df: pd.DataFrame, X: pd.DataFrame, events: pd.DataFrame, train_end: pd.Timestamp,
            params: pd.Series | None = None):
        self.train_end = train_end
        self.sarimax_params = (fit_daily_model(daily_frame(df, events), train_end)
                               if params is None else params)
        self.level = daily_level(df, events, params=self.sarimax_params)
        offset = np.log(self.level.clip(lower=0.5))
        mask = _train_mask(df, X, SHAPE_FEATURES, train_end)
        self.model = lgb.LGBMRegressor(**PARAMS).fit(
            X.loc[mask, SHAPE_FEATURES], df.loc[mask, "offered"],
            init_score=offset[mask], categorical_feature=CATEGORICAL)
        return self

    def predict(self, X: pd.DataFrame, df: pd.DataFrame | None = None,
                events: pd.DataFrame | None = None) -> pd.Series:
        """Sans df : sur les donnees d'entrainement. Avec df : sur de nouvelles donnees
        (par exemple l'historique prolonge d'un jour futur), parametres figes."""
        level = self.level if df is None else daily_level(df, events, params=self.sarimax_params)
        offset = np.log(level.reindex(X.index).clip(lower=0.5))
        raw = self.model.predict(X[SHAPE_FEATURES], raw_score=True)
        return pd.Series(np.exp(raw + offset), index=X.index, name="hybride")