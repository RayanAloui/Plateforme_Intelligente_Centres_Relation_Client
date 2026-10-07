"""Explicabilite (module 17) : pourquoi la prevision est-elle elevee ?

La prevision du champion s'ecrit :  volume = niveau du jour (SARIMAX) x forme (LightGBM).
Pour la partie LightGBM, on calcule les valeurs de SHAP exactes des arbres (TreeSHAP,
fourni nativement par LightGBM avec pred_contrib=True) : chaque variable recoit une
contribution additive sur l'echelle logarithmique, donc MULTIPLICATIVE sur le volume.
  exemple : "lundi"  ->  x 1,32  ->  +32 % par rapport a une demi-heure moyenne
"""
import numpy as np
import pandas as pd

from crc.forecasting.ml import SHAPE_FEATURES, HybridForecaster

LABELS = {
    "period": "heure de la journee", "period_sin": "heure de la journee", "period_cos": "heure de la journee",
    "dow": "jour de la semaine", "is_weekend": "jour de la semaine",
    "month": "saison", "doy_sin": "saison", "doy_cos": "saison",
    "is_holiday": "jour ferie", "post_holiday": "lendemain de ferie",
    "is_school_holiday": "vacances scolaires", "campaign": "campagne commerciale",
}


def contributions(hybrid: HybridForecaster, X: pd.DataFrame) -> pd.DataFrame:
    """Contribution multiplicative (en %) de chaque facteur, regroupee par theme lisible."""
    raw = hybrid.model.predict(X[SHAPE_FEATURES], pred_contrib=True)[:, :-1]     # sans le terme de base
    phi = pd.DataFrame(raw, index=X.index, columns=SHAPE_FEATURES)
    grouped = phi.T.groupby(pd.Series(LABELS)).sum().T                            # somme en log = produit
    return 100 * (np.exp(grouped) - 1)


def explain_interval(hybrid: HybridForecaster, X: pd.DataFrame, ts: pd.Timestamp) -> pd.DataFrame:
    """Explication d'une demi-heure : niveau du jour, puis facteurs du plus au moins influent."""
    c = contributions(hybrid, X.loc[[ts]]).iloc[0]
    c = c.reindex(c.abs().sort_values(ascending=False).index)
    return pd.DataFrame({"facteur": c.index, "effet %": c.round(1).to_numpy()})


def global_importance(hybrid: HybridForecaster, X: pd.DataFrame) -> pd.Series:
    """Importance moyenne de chaque facteur (moyenne des effets absolus, en %)."""
    return contributions(hybrid, X).abs().mean().sort_values(ascending=False).round(1)