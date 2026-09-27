"""Prevision probabiliste : passer d'un chiffre a une distribution.

Le champion donne mu_t, le volume attendu. Autour, deux sources d'incertitude :

  1. l'erreur sur le NIVEAU DU JOUR, commune a toute la journee
     (un jour plus charge que prevu l'est du matin au soir)     -> D_d ~ LogNormale(sigma)
  2. le hasard d'un intervalle a l'autre, surdisperse (EDA, fig. 07) -> G_t ~ Gamma(k, 1/k)

    Y_t ~ Poisson( mu_t x D_d x G_t )

C'est un processus de Cox, la meme structure que le generateur : le modele
predictif est coherent avec la realite qu'il decrit. Il servira directement
au Monte Carlo de la Phase 3, qui tirera des journees entieres de scenarios.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class CoxPredictive:
    day_sigma: float          # ecart-type (log) de l'erreur sur le niveau du jour
    gamma_shape: float        # k : plus il est grand, plus on se rapproche de Poisson

    @classmethod
    def calibrate(cls, mu: pd.Series, y: pd.Series, dates: pd.Series) -> "CoxPredictive":
        """Estimation sur des previsions HORS ECHANTILLON (jamais sur l'entrainement du modele)."""
        day_ratio = y.groupby(dates).sum() / mu.groupby(dates).sum()
        day_sigma = float(np.log(day_ratio).std())
        # Une fois l'erreur du jour retiree, il reste la surdispersion intra-journaliere :
        # Var(Y | m) = m + m^2 / k  ->  estimation de k par la methode des moments
        m = mu * dates.map(day_ratio).to_numpy()
        excess = ((y - m) ** 2 - m).sum()
        gamma_shape = float((m ** 2).sum() / max(excess, 1e-9))
        return cls(day_sigma, gamma_shape)

    def sample(self, mu: pd.Series, dates: pd.Series, n: int, rng: np.random.Generator) -> np.ndarray:
        """n scenarios complets (n x T), avec une erreur de niveau partagee par chaque jour."""
        codes, uniques = pd.factorize(dates)
        s, k = self.day_sigma, self.gamma_shape
        day = rng.lognormal(-s ** 2 / 2, s, size=(n, len(uniques)))[:, codes]
        gamma = rng.gamma(k, 1 / k, size=(n, len(mu)))
        return rng.poisson(mu.to_numpy()[None, :] * day * gamma)

    def quantiles(self, mu: pd.Series, dates: pd.Series, probs=(0.1, 0.5, 0.9),
                  n: int = 2000, seed: int = 0, chunk: int = 2000) -> pd.DataFrame:
        """Quantiles par simulation (une colonne par probabilite), calcules par blocs."""
        rng = np.random.default_rng(seed)
        out = []
        for i in range(0, len(mu), chunk):
            sims = self.sample(mu.iloc[i:i + chunk], dates.iloc[i:i + chunk], n, rng)
            out.append(np.quantile(sims, probs, axis=0).T)
        return pd.DataFrame(np.vstack(out), index=mu.index, columns=list(probs))


def poisson_quantiles(mu: pd.Series, probs=(0.1, 0.5, 0.9)) -> pd.DataFrame:
    """Reference naive : suppose des arrivees de Poisson et une prevision parfaite du niveau."""
    return pd.DataFrame({p: stats.poisson.ppf(p, mu) for p in probs}, index=mu.index)