"""Metriques d'evaluation des previsions ponctuelles."""
import numpy as np
import pandas as pd

MAPE_MIN_VOLUME = 20      # la MAPE explose sur les petits volumes nocturnes : on l'y restreint


def evaluate(y: pd.Series, yhat: pd.Series) -> dict:
    y, yhat = y.astype(float), yhat.astype(float)
    e = yhat - y
    big = y >= MAPE_MIN_VOLUME
    return {
        "MAE": e.abs().mean(),
        "RMSE": np.sqrt((e ** 2).mean()),
        "WAPE_%": 100 * e.abs().sum() / y.sum(),
        "MAPE_%": 100 * (e[big].abs() / y[big]).mean(),
        "biais_%": 100 * e.sum() / y.sum(),
    }


def comparison_table(y: pd.Series, predictions: dict[str, pd.Series]) -> pd.DataFrame:
    rows = {name: evaluate(y, p.reindex(y.index)) for name, p in predictions.items()}
    return pd.DataFrame(rows).T.round(2).sort_values("WAPE_%")