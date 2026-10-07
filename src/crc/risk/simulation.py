"""Monte Carlo du risque operationnel (modules 11 et 12).

Pour une journee et un planning donnes, on tire des milliers de journees possibles :
  - la demande        : processus de Cox calibre en Phase 2 (erreur de niveau du jour + surdispersion)
  - les absences      : taux d'absence journalier tire dans l'historique (jours exceptionnels compris)
  - la duree d'appel  : AHT prevue avec un alea de 5 %
puis l'Erlang A transforme chaque scenario en attente, abandons, service level et pertes en euros.
On en deduit la perte attendue, la VaR et l'Expected Shortfall de la journee.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from crc.forecasting.probabilistic import CoxPredictive
from crc.risk.costs import INTERVAL_SECONDS, queue_losses


def var(losses: np.ndarray, level: float = 0.95) -> float:
    """Value at Risk : perte qui n'est depassee que dans (1 - level) des scenarios."""
    return float(np.quantile(losses, level))


def expected_shortfall(losses: np.ndarray, level: float = 0.95) -> float:
    """Perte moyenne dans les (1 - level) pires scenarios."""
    v = var(losses, level)
    return float(losses[losses >= v].mean())


@dataclass
class OperationalRiskModel:
    predictive: CoxPredictive
    absence_rates: np.ndarray          # taux d'absence journaliers observes (historique)
    patience: float                    # patience moyenne des clients (estimee)
    costs: dict
    aht_sigma: float = 0.05

    def simulate(self, mu: pd.Series, aht: pd.Series, scheduled, n: int = 1000, seed: int = 0) -> dict:
        """n scenarios d'une ou plusieurs journees. Retourne des tableaux (n x intervalles)."""
        rng = np.random.default_rng(seed)
        dates = pd.Series(mu.index.date, index=mu.index)
        codes, uniques = pd.factorize(dates)
        arrivals = self.predictive.sample(mu, dates, n, rng)
        absence = rng.choice(self.absence_rates, size=(n, len(uniques)))[:, codes]
        present = np.maximum(rng.binomial(np.broadcast_to(np.asarray(scheduled, dtype=int), arrivals.shape),
                                          1 - absence), 1)
        s = self.aht_sigma
        aht_s = aht.to_numpy()[None, :] * rng.lognormal(-s ** 2 / 2, s, size=arrivals.shape)
        out = queue_losses(arrivals, present, aht_s, self.patience, self.costs, rng)
        out.update({"arrivees": arrivals, "presents": present})
        return out

    def day_risk(self, mu: pd.Series, aht: pd.Series, scheduled, n: int = 1000, seed: int = 0) -> dict:
        """Mesures de risque d'une journee pour un planning donne."""
        sim = self.simulate(mu, aht, scheduled, n, seed)
        daily = sim["perte"].sum(axis=1)
        staff = self.costs["cost_agent_hour"] * INTERVAL_SECONDS / 3600 * np.asarray(scheduled).sum()
        return {
            "cout_agents": float(staff),
            "perte_attendue": float(daily.mean()),
            "VaR95": var(daily, 0.95), "ES95": expected_shortfall(daily, 0.95),
            "VaR99": var(daily, 0.99), "ES99": expected_shortfall(daily, 0.99),
            "proba_sous_capacite": sim["sous_capacite"].mean(axis=0),      # par intervalle
            "service_level_attendu": float(np.average(sim["service_level"], weights=sim["arrivees"] + 1e-9)),
            "pertes_scenarios": daily,
        }


def kupiec_test(exceedances: int, n: int, level: float) -> float:
    """Test de Kupiec (proportion of failures) : p-valeur de l'hypothese 'la VaR est bien calibree'."""
    from scipy import stats
    p, x = 1 - level, exceedances
    phat = x / n
    ll0 = (n - x) * np.log(1 - p) + x * np.log(p)
    ll1 = (n - x) * np.log(1 - phat) + (x * np.log(phat) if x > 0 else 0.0) if 0 < phat < 1 else 0.0
    return float(1 - stats.chi2.cdf(-2 * (ll0 - ll1), df=1))