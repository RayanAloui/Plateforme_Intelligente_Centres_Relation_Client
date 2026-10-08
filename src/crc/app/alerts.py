"""Systeme d'alertes intelligent (module 18).

Chaque demi-heure recoit un niveau, a partir de deux signaux :
  - le RISQUE prevu la veille : probabilite de sous-capacite avec le planning applique
  - l'ANOMALIE constatee le jour meme : volume hors de la fourchette (etape 2.7)

    Eleve  : P(sous-capacite) >= 20 %  ou anomalie forte    -> intervention recommandee
    Moyen  : P(sous-capacite) >= 10 %  ou anomalie moderee  -> surveillance recommandee
    Faible : sinon                                           -> aucune intervention

Les demi-heures consecutives de meme niveau sont regroupees en une seule alerte, avec une
recommandation chiffree : le renfort qui ramene le planning au niveau du planning optimise.
"""
import numpy as np
import pandas as pd

HIGH, MEDIUM = 0.20, 0.10
LEVELS = {0: "Faible", 1: "Moyen", 2: "Eleve"}


def interval_levels(p_undercap: pd.Series, anomaly: pd.Series | None = None,
                    high: float = HIGH, medium: float = MEDIUM) -> pd.Series:
    """Niveau par demi-heure ; les seuils viennent des parametres de la plateforme."""
    level = np.where(p_undercap >= high, 2, np.where(p_undercap >= medium, 1, 0))
    if anomaly is not None:
        level = np.maximum(level, anomaly.reindex(p_undercap.index).fillna(0).to_numpy().astype(int))
    return pd.Series(level, index=p_undercap.index, name="niveau")


def build_alerts(level: pd.Series, p_undercap: pd.Series, expected_loss: pd.Series,
                 applied: pd.Series, optimal: pd.Series) -> pd.DataFrame:
    """Regroupe les demi-heures de niveau Moyen ou Eleve en periodes d'alerte."""
    run = (level != level.shift()).cumsum()
    rows = []
    for _, block in level[level > 0].groupby(run[level > 0]):
        idx = block.index
        rows.append({
            "niveau": LEVELS[int(block.iloc[0])],
            "debut": idx[0], "fin": idx[-1] + pd.Timedelta(minutes=30),
            "proba_sous_capacite_max": float(p_undercap.loc[idx].max()),
            "perte_attendue": float(expected_loss.loc[idx].sum()),
            "renfort_recommande": int(max(0, (optimal.loc[idx] - applied.loc[idx]).max())),
        })
    alerts = pd.DataFrame(rows, columns=["niveau", "debut", "fin", "proba_sous_capacite_max",
                                         "perte_attendue", "renfort_recommande"])
    return alerts.sort_values(["niveau", "perte_attendue"], ascending=[True, False]).reset_index(drop=True)


def message(alert: pd.Series) -> str:
    """Texte de l'alerte, au format du document de cadrage."""
    title = {"Eleve": "Risque élevé détecté", "Moyen": "Risque moyen : surveillance recommandée"}[alert["niveau"]]
    reco = (f"+{alert['renfort_recommande']} agents" if alert["renfort_recommande"] > 0
            else "aucun renfort nécessaire, surveiller")
    loss = f"{alert['perte_attendue']:,.0f} EUR".replace(",", " ")
    return (f"{title}\n"
            f"Période : {alert['debut']:%Hh%M} - {alert['fin']:%Hh%M}\n"
            f"Probabilité de sous-capacité : {100 * alert['proba_sous_capacite_max']:.0f} %\n"
            f"Perte attendue : {loss}\n"
            f"Recommandation : {reco}")
