"""Modeles de reference, sans apprentissage : la barre a franchir."""
import pandas as pd


def baselines(X: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "Naif veille": X["lag_1d"],
        "Naif semaine": X["lag_1w"],
        "Moyenne 4 semaines": X["mean_4w"],
    }