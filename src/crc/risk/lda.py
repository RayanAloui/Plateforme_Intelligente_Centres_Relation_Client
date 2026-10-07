"""Approche actuarielle frequence x severite (modules 8, 9, 10 et 12).

C'est la "Loss Distribution Approach" (LDA) du risque operationnel bancaire (Bale II),
appliquee au centre de relation client :
  1. definir chaque risque comme un evenement observable dans l'historique
  2. FREQUENCE : nombre d'evenements par mois    -> Poisson ou binomiale negative
  3. SEVERITE  : cout d'un evenement en euros    -> lognormale, gamma, Weibull ou Pareto
  4. Monte Carlo de la perte mensuelle composee  -> perte attendue, VaR 99 %, ES 99 %
"""
import numpy as np
import pandas as pd
from scipy import stats

from crc.risk.costs import INTERVAL_SECONDS

# Pareto de type II (Lomax) : la version a queue epaisse qui demarre a 0, adaptee a des couts.
SEVERITY_LAWS = {"lognormale": stats.lognorm, "gamma": stats.gamma,
                 "Weibull": stats.weibull_min, "Pareto (Lomax)": stats.lomax}


def risk_masks(df: pd.DataFrame, losses: pd.DataFrame, costs: dict, reference: pd.DataFrame) -> dict:
    """Les six risques du document de cadrage, traduits en regles observables.

    reference : periode servant a fixer les seuils (budget), pour ne pas utiliser l'avenir.
    Les risques 4 et 5 sont journaliers, les autres par demi-heure.
    """
    load = df["offered"] * df["avg_handle_seconds"] / INTERVAL_SECONDS
    expected = pd.concat([df["offered"].shift(336 * k) for k in range(1, 5)], axis=1).mean(axis=1)

    day_cost = (losses["perte"] + losses["cout_agents"]).groupby(df["date"]).sum()
    ref_cost = (losses.loc[reference.index, "perte"] + losses.loc[reference.index, "cout_agents"]) \
        .groupby(reference["date"]).sum()
    ref_dow = pd.Series(pd.to_datetime(ref_cost.index).dayofweek, index=ref_cost.index)
    budget = (1.15 * ref_cost.groupby(ref_dow).median())
    dows = pd.Series(pd.to_datetime(day_cost.index).dayofweek, index=day_cost.index)
    over_budget = day_cost > dows.map(budget)

    absence = df["agents_absent"].groupby(df["date"]).sum() / df["agents_scheduled"].groupby(df["date"]).sum()
    to_intervals = lambda day_flags: df["date"].map(day_flags).fillna(False).astype(bool)
    return {
        "1 Surcharge des agents": df["occupancy"] >= 0.95,
        "2 Sous-capacite": load > df["agents_present"],
        "3 Degradation du service": (df["service_level"] < costs["sla_target_ratio"]) & (df["offered"] >= 20),
        "4 Depassement du budget": to_intervals(over_budget),
        "5 Absence exceptionnelle": to_intervals(absence >= 0.15),
        "6 Pic exceptionnel de demande": (df["offered"] > 1.5 * expected) & (df["offered"] >= 50),
    }


def extract_events(mask: pd.Series, loss: pd.Series, daily: bool) -> pd.DataFrame:
    """Un evenement = une suite d'intervalles consecutifs en risque (ou une journee en risque)."""
    if daily:
        group = pd.Series(mask.index.normalize(), index=mask.index)
    else:
        group = (mask != mask.shift(fill_value=False)).cumsum()
    m = mask.to_numpy()
    ev = pd.DataFrame({"debut": mask.index[m], "groupe": group[m].to_numpy(), "perte": loss[m].to_numpy()})
    return ev.groupby("groupe").agg(debut=("debut", "first"), duree=("perte", "size"),
                                    severite=("perte", "sum")).reset_index(drop=True)


def fit_frequency(counts: np.ndarray) -> dict:
    """Poisson si la variance est compatible avec la moyenne, binomiale negative sinon."""
    m, v, k = counts.mean(), counts.var(ddof=1), len(counts)
    dispersion = v / m if m > 0 else 1.0
    p_value = 1 - stats.chi2.cdf((k - 1) * dispersion, df=k - 1)    # test de surdispersion
    if p_value < 0.05 and v > m:
        r = m ** 2 / (v - m)
        return {"loi": "binomiale negative", "moyenne": m, "dispersion": dispersion,
                "p_surdispersion": p_value, "sampler": lambda rng, n: rng.negative_binomial(r, r / (r + m), n)}
    return {"loi": "Poisson", "moyenne": m, "dispersion": dispersion, "p_surdispersion": p_value,
            "sampler": lambda rng, n: rng.poisson(m, n)}


def fit_severity(x: np.ndarray) -> pd.DataFrame:
    """Ajuste les quatre lois candidates par maximum de vraisemblance.

    Choix par AIC, parmi les lois dont la moyenne ajustee reste coherente avec la moyenne
    observee (a +/- 25 %) : une loi a queue trop epaisse peut gagner l'AIC grace aux petites
    valeurs tout en produisant une perte moyenne absurde.
    Le test de Kolmogorov-Smirnov est indique a titre informatif : avec des milliers
    d'evenements, il rejette toute loi parametrique au moindre ecart.
    """
    rows = []
    for name, law in SEVERITY_LAWS.items():
        params = law.fit(x, floc=0)
        ll = np.sum(law.logpdf(x, *params))
        mean = law.mean(*params)
        rows.append({"loi": name, "params": params, "AIC": 2 * 2 - 2 * ll,
                     "p_KS": stats.kstest(x, law.cdf, args=params).pvalue,
                     "moyenne_ajustee / observee": mean / x.mean() if np.isfinite(mean) else np.inf})
    table = pd.DataFrame(rows)
    table["coherente"] = table["moyenne_ajustee / observee"].between(0.75, 1.25)
    return table.sort_values(["coherente", "AIC"], ascending=[False, True]).reset_index(drop=True)


def compound_losses(freq: dict, law, params, n: int = 50_000, seed: int = 0) -> np.ndarray:
    """Perte mensuelle simulee : somme d'un nombre aleatoire de severites aleatoires."""
    rng = np.random.default_rng(seed)
    counts = freq["sampler"](rng, n)
    sev = law.rvs(*params, size=int(counts.sum()), random_state=rng)
    month = np.repeat(np.arange(n), counts)
    return np.bincount(month, weights=sev, minlength=n)


def lda_table(df: pd.DataFrame, losses: pd.DataFrame, costs: dict, reference: pd.DataFrame) -> tuple:
    """Une ligne par risque : frequence, severite, perte attendue, VaR et ES mensuelles."""
    rows, fits = [], {}
    months = df.index.to_period("M")
    for name, mask in risk_masks(df, losses, costs, reference).items():
        daily = name.startswith(("4", "5"))
        ev = extract_events(mask, losses["perte"], daily)
        ev = ev[ev["severite"] > 0]
        counts = ev["debut"].dt.to_period("M").value_counts().reindex(months.unique(), fill_value=0).to_numpy()
        freq = fit_frequency(counts)
        sev = fit_severity(ev["severite"].to_numpy())
        best = sev.iloc[0]
        monthly = compound_losses(freq, SEVERITY_LAWS[best["loi"]], best["params"])
        v99 = np.quantile(monthly, 0.99)
        fits[name] = {"evenements": ev, "severite": sev, "frequence": freq, "mensuel": monthly}
        rows.append({
            "risque": name, "evenements": len(ev), "frequence / mois": round(freq["moyenne"], 1),
            "loi frequence": freq["loi"], "severite moyenne EUR": round(ev["severite"].mean()),
            "loi severite (AIC)": best["loi"], "p KS": round(best["p_KS"], 3),
            "perte attendue / mois EUR": round(monthly.mean()),
            "VaR99 / mois EUR": round(v99), "ES99 / mois EUR": round(monthly[monthly >= v99].mean()),
        })
    return pd.DataFrame(rows).set_index("risque"), fits