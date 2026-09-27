"""Tournoi des modeles de prevision sur la periode de validation.

    python -m crc.forecasting.compare

Le tableau s'enrichit a chaque etape de la Phase 2.
"""
from pathlib import Path

import pandas as pd

from crc.datasets import load_history
from crc.db import read_sql
from crc.forecasting.baselines import baselines
from crc.forecasting.features import build_features
from crc.forecasting.metrics import comparison_table
from crc.forecasting.statistical import top_down_forecast
from crc.splits import SPLITS, select

TRUTH = Path("data/truth/ground_truth.parquet")
REPORT = Path("outputs/forecast_comparison.csv")


def load_inputs():
    df = load_history()
    events = read_sql("SELECT * FROM ref.events")
    return df, events, build_features(df, events)


def run() -> pd.DataFrame:
    df, events, X = load_inputs()
    # Evaluation sur la validation, hors valeurs reconstituees par le nettoyage
    val = select(df, "validation")
    val = val[~val["is_imputed"]]
    y = val["offered"]

    predictions = baselines(X)

    # Modeles entraines uniquement sur la periode d'entrainement
    train_end = SPLITS["validation"][0]
    predictions["SARIMAX journalier + profil"] = top_down_forecast(df, events, train_end)

    # Reference theorique : un oracle qui connaitrait l'intensite reelle.
    # Aucun modele ne peut faire mieux en moyenne : c'est le hasard irreductible.
    if TRUTH.exists():
        truth = pd.read_parquet(TRUTH).set_index("ts")
        predictions["(Oracle - plancher theorique)"] = truth["lambda_true"]

    table = comparison_table(y, predictions)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(REPORT)
    print(f"Validation : {len(y)} intervalles ({y.index.min():%d/%m/%Y} -> {y.index.max():%d/%m/%Y})\n")
    print(table.to_string())
    return table


if __name__ == "__main__":
    run()