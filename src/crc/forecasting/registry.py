"""Registre des modeles de prevision (etape 2.8) : entrainer, sauvegarder, recharger.

    python -m crc.forecasting.registry

Produit dans models/ :
  forecast_AAAAMMJJ.joblib  le modele complet (SARIMAX + LightGBM + incertitude)
  forecast_AAAAMMJJ.json    sa fiche d'identite, lisible par un humain

La date du nom est la date de coupure : le modele n'a vu aucune donnee posterieure.
Politique : reentrainement mensuel (conclusion de l'evaluation glissante, etape 2.5).
"""
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd

from crc.datagen.calendar import build_calendar
from crc.forecasting.anomalies import AnomalyDetector
from crc.forecasting.metrics import evaluate
from crc.forecasting.ml import PARAMS, SHAPE_FEATURES, HybridForecaster
from crc.forecasting.probabilistic import CoxPredictive
from crc.forecasting.statistical import ORDER, PROFILE_WEEKS, SEASONAL_ORDER

MODELS_DIR = Path("models")
AHT_WEEKS = 8                       # mediane des 8 memes demi-heures precedentes (erreur ~5 %)
CALIBRATION_MONTHS = 12


def aht_forecast(df: pd.DataFrame, weeks: int = AHT_WEEKS) -> pd.Series:
    """AHT attendue : mediane de la meme demi-heure sur les semaines precedentes (robuste aux incidents)."""
    aht = df["avg_handle_seconds"].astype(float)
    lags = pd.concat([aht.shift(336 * k) for k in range(1, weeks + 1)], axis=1)
    return lags.median(axis=1).rename("aht_attendue")


def future_frame(df: pd.DataFrame, days: int, granularity: int = 30) -> pd.DataFrame:
    """Prolonge l'historique de `days` jours futurs : calendrier connu, volumes inconnus (NaN)."""
    start = (df.index[-1] + pd.Timedelta(minutes=granularity)).date()
    cal = build_calendar(start, start + pd.Timedelta(days=days - 1), granularity).set_index("ts")
    future = cal.reindex(columns=df.columns)
    future["is_imputed"] = False
    return pd.concat([df, future.astype(df.dtypes.to_dict(), errors="ignore")])


@dataclass
class ForecastBundle:
    cutoff: pd.Timestamp
    hybrid: HybridForecaster
    predictive: CoxPredictive
    card: dict = field(default_factory=dict)

    @property
    def version(self) -> str:
        return f"forecast_{self.cutoff:%Y%m%d}"

    def forecast(self, df: pd.DataFrame, events: pd.DataFrame, X: pd.DataFrame) -> pd.DataFrame:
        """Volume attendu et AHT attendue pour chaque intervalle de df (passe ou futur)."""
        return pd.DataFrame({"volume_attendu": self.hybrid.predict(X, df, events),
                             "aht_attendue": aht_forecast(df)})

    def detector(self) -> AnomalyDetector:
        return AnomalyDetector(self.predictive)


def build_bundle(df, events, X, cutoff: pd.Timestamp, rolling_mu: pd.Series,
                 fingerprint: str | None = None) -> ForecastBundle:
    """Entraine le champion jusqu'a `cutoff` et calibre son incertitude.

    rolling_mu : previsions HORS ECHANTILLON du champion (reentraine chaque mois) sur les
    mois precedant cutoff. Premiere moitie -> calibration de controle, seconde moitie ->
    verification ; l'incertitude finale est ensuite calibree sur l'ensemble.
    """
    hybrid = HybridForecaster().fit(df, X, events, cutoff)

    idx = rolling_mu.index
    y = df.loc[idx, "offered"].astype(float)
    dates = pd.Series(df.loc[idx, "date"].to_numpy(), index=idx)
    ok = ~df.loc[idx, "is_imputed"].to_numpy()
    months = pd.DatetimeIndex(idx).to_period("M").unique()
    middle = months[len(months) // 2].to_timestamp()
    first, second = ok & (idx < middle), ok & (idx >= middle)

    control = CoxPredictive.calibrate(rolling_mu[first], y[first], dates[first])
    q = control.quantiles(rolling_mu[second], dates[second], (0.1, 0.9))
    coverage80 = float(((y[second] >= q[0.1]) & (y[second] <= q[0.9])).mean())
    point = evaluate(y[second], rolling_mu[second])
    predictive = CoxPredictive.calibrate(rolling_mu[ok], y[ok], dates[ok])

    card = {
        "version": f"forecast_{cutoff:%Y%m%d}",
        "cree_le": datetime.now().isoformat(timespec="seconds"),
        "donnees": {"coupure": f"{cutoff:%Y-%m-%d}", "debut_historique": f"{df.index[0]:%Y-%m-%d}",
                    "empreinte": fingerprint},
        "modele_champion": {
            "nom": "Hybride SARIMAX + LightGBM",
            "sarimax": {"ordre": ORDER, "ordre_saisonnier": SEASONAL_ORDER, "cible": "log(total journalier)"},
            "lightgbm": {k: v for k, v in PARAMS.items() if k != "verbose"},
            "variables_lightgbm": SHAPE_FEATURES,
            "profil_intra_journalier_semaines": PROFILE_WEEKS,
        },
        "incertitude": {"modele": "processus de Cox", "sigma_jour": round(predictive.day_sigma, 4),
                        "k_surdispersion": round(predictive.gamma_shape, 2)},
        "aht": {"methode": f"mediane des {AHT_WEEKS} memes demi-heures precedentes"},
        "detection_anomalies": {"seuil_modere": 0.99, "seuil_fort": 0.999},
        "performances_hors_echantillon": {
            "periode": f"{middle:%Y-%m-%d} -> {idx[-1]:%Y-%m-%d}",
            "WAPE_%": round(point["WAPE_%"], 2), "biais_%": round(point["biais_%"], 2),
            "couverture_fourchette_80_%": round(100 * coverage80, 1),
        },
        "secours": "Moyenne 4 semaines (si le champion echoue ou devient moins bon : derive)",
        "politique": "reentrainement mensuel",
        "periode_de_test": "non evaluee - reservee a l'experience finale",
    }
    return ForecastBundle(cutoff, hybrid, predictive, card)


def save_bundle(bundle: ForecastBundle, directory: Path = MODELS_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{bundle.version}.joblib"
    joblib.dump(bundle, path)
    (directory / f"{bundle.version}.json").write_text(
        json.dumps(bundle.card, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def load_bundle(version: str | None = None, directory: Path = MODELS_DIR) -> ForecastBundle:
    """Charge une version precise, ou la plus recente."""
    if version is None:
        candidates = sorted(directory.glob("forecast_*.joblib"))
        if not candidates:
            raise FileNotFoundError("Aucun modele : lancer  python -m crc.forecasting.registry")
        return joblib.load(candidates[-1])
    return joblib.load(directory / f"{version}.joblib")


def run(cutoff: pd.Timestamp | None = None) -> ForecastBundle:
    from crc.forecasting.compare import load_inputs
    from crc.forecasting.intervals import rolling_forecast
    from crc.rebuild import fingerprint
    from crc.splits import SPLITS

    cutoff = cutoff or SPLITS["test"][0]
    df, events, X = load_inputs()
    start = cutoff - pd.DateOffset(months=CALIBRATION_MONTHS)
    print(f"Previsions hors echantillon {start:%Y-%m} -> {cutoff:%Y-%m} (reentrainement mensuel)...")
    rolling_mu = rolling_forecast(df, events, X, start, cutoff)
    bundle = build_bundle(df, events, X, cutoff, rolling_mu, fingerprint())
    path = save_bundle(bundle)
    print(f"\nModele sauvegarde : {path}\n")
    print(json.dumps(bundle.card, indent=2, ensure_ascii=False, default=str))
    return bundle


if __name__ == "__main__":
    run()