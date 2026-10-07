"""Tableau de bord de la plateforme (module 19).

    streamlit run src/crc/app/dashboard.py

Prerequis : python -m crc.app.prepare  (prepare les donnees du mode rejeu).
"""
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from crc.app.alerts import LEVELS, message
from crc.app.explain import explain_interval, global_importance
from crc.optim.whatif import Scenario, what_if

APP_DIR, OUT = Path("data/app"), Path("outputs")
COLORS = {"baseline": "#8c8c8c", "ia": "#1f77b4", "optimise": "#2ca02c"}
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

st.set_page_config(page_title="Plateforme CRC - prevision et risque", layout="wide")


def eur(v: float) -> str:
    return f"{v:,.0f} EUR".replace(",", " ")


@st.cache_data
def load_tables():
    intervals = pd.read_parquet(APP_DIR / "intervalles.parquet")
    days = pd.read_parquet(APP_DIR / "jours.parquet")
    alerts = pd.read_parquet(APP_DIR / "alertes.parquet")
    losses = dict(np.load(APP_DIR / "pertes_scenarios.npz"))
    return intervals, days, alerts, losses


@st.cache_resource
def load_models():
    return joblib.load(APP_DIR / "modeles.joblib")


@st.cache_data(show_spinner="Calcul du scenario (quelques secondes)...")
def run_what_if(day: str, volume: float, absence: float, budget: float, alpha: float) -> dict:
    m = load_models()
    sl = slice(pd.Timestamp(day), pd.Timestamp(day) + pd.Timedelta(hours=23.5))
    r = what_if(m["risk_model"], m["mu"].loc[sl], m["aht"].loc[sl],
                Scenario(volume_factor=volume, extra_absence=absence, budget_cut=budget or None, alpha=alpha))
    return r


if not (APP_DIR / "jours.parquet").exists():
    st.error("Donnees absentes : lancer d'abord  python -m crc.app.prepare")
    st.stop()

intervals, days, alerts, losses = load_tables()

# --- Barre laterale ------------------------------------------------------------------------------
st.sidebar.title("Plateforme CRC")
page = st.sidebar.radio("Page", ["Vue d'ensemble", "Prevision", "Risque et planning", "What-if"])
first, last = days.index.min().date(), days.index.max().date()
day = pd.Timestamp(st.sidebar.date_input("Journee", value=first, min_value=first, max_value=last))
st.sidebar.caption("Mode rejeu : decembre 2024. Chaque journee montre ce que la plateforme "
                   "annoncait la veille, puis ce qui s'est reellement passe.")

d = days.loc[day]
iv = intervals.loc[day: day + pd.Timedelta(hours=23.5)]
day_alerts = alerts[alerts["jour"] == day]
title_day = f"{JOURS[day.dayofweek]} {day:%d/%m/%Y}"


# --- Page 1 : vue d'ensemble -------------------------------------------------------------------------
if page == "Vue d'ensemble":
    st.title(f"Vue d'ensemble - {title_day}")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Volume prevu", f"{iv['volume_prevu'].sum():,.0f} appels".replace(",", " "))
    c2.metric("Cout agents (optimise)", eur(d["optimise_cout_agents"]),
              eur(d["optimise_cout_agents"] - d["baseline_cout_agents"]) + " vs actuel", delta_color="inverse")
    c3.metric("Perte attendue (optimise)", eur(d["optimise_perte_attendue"]),
              eur(d["optimise_perte_attendue"] - d["baseline_perte_attendue"]) + " vs actuel",
              delta_color="inverse")
    c4.metric("VaR 95 % (optimise)", eur(d["optimise_VaR95"]))
    c5.metric("Niveau de risque du jour", LEVELS[int(d["niveau_max"])])

    st.subheader("Alertes de la journee (planning actuel)")
    if day_alerts.empty:
        st.success("Aucune alerte : risque faible sur toute la journee.")
    for _, a in day_alerts.iterrows():
        (st.error if a["niveau"] == "Eleve" else st.warning)(message(a).replace("\n", "  \n"))

    fig = go.Figure()
    fig.add_scatter(x=iv.index, y=iv["volume_prevu"], name="prevu la veille", line=dict(width=3))
    fig.add_scatter(x=iv.index, y=iv["volume_observe"], name="observe", line=dict(color="black", width=1))
    fig.update_layout(title="Volume d'appels par demi-heure", height=330, margin=dict(t=40, b=10))
    st.plotly_chart(fig, use_container_width=True)

    if (OUT / "experience_finale.csv").exists():
        with st.expander("Resultats de l'experience finale (juillet - decembre 2024)"):
            st.dataframe(pd.read_csv(OUT / "experience_finale.csv", index_col=0).round(1),
                         use_container_width=True)


# --- Page 2 : prevision ---------------------------------------------------------------------------------
elif page == "Prevision":
    st.title(f"Prevision - {title_day}")
    fig = go.Figure()
    fig.add_scatter(x=iv.index, y=iv["q99"], line=dict(width=0), showlegend=False, hoverinfo="skip")
    fig.add_scatter(x=iv.index, y=iv["q01"], fill="tonexty", fillcolor="rgba(31,119,180,0.15)",
                    line=dict(width=0), name="fourchette 98 %")
    fig.add_scatter(x=iv.index, y=iv["q90"], line=dict(width=0), showlegend=False, hoverinfo="skip")
    fig.add_scatter(x=iv.index, y=iv["q10"], fill="tonexty", fillcolor="rgba(31,119,180,0.35)",
                    line=dict(width=0), name="fourchette 80 %")
    fig.add_scatter(x=iv.index, y=iv["volume_prevu"], name="prevision", line=dict(color="#1f77b4", width=2))
    fig.add_scatter(x=iv.index, y=iv["volume_observe"], mode="markers", name="observe",
                    marker=dict(color="black", size=5))
    anomalous = iv[iv["anomalie"] > 0]
    fig.add_scatter(x=anomalous.index, y=anomalous["volume_observe"], mode="markers", name="anomalie",
                    marker=dict(color="red", size=11, symbol="circle-open", line=dict(width=2)))
    fig.update_layout(title="Prevision a J+1 et fourchettes d'incertitude", height=420, margin=dict(t=40))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Pourquoi cette prevision ?")
    models = load_models()
    times = [t.strftime("%H:%M") for t in iv.index]
    chosen = st.select_slider("Demi-heure", options=times, value="10:30")
    ts = pd.Timestamp(f"{day:%Y-%m-%d} {chosen}")
    level = models["hybrid"].level.loc[ts] * 48
    col1, col2 = st.columns([1, 2])
    col1.metric("Prevision", f"{iv.loc[ts, 'volume_prevu']:.0f} appels")
    col1.metric("Volume total prevu du jour (SARIMAX)", f"{level:,.0f} appels".replace(",", " "))
    col1.caption("Le niveau du jour integre deja la tendance, le jour de la semaine et le calendrier. "
                 "LightGBM le repartit ensuite selon les facteurs ci-contre.")
    exp = explain_interval(models["hybrid"], models["X"], ts)
    fig = go.Figure(go.Bar(x=exp["effet %"], y=exp["facteur"], orientation="h",
                           marker_color=np.where(exp["effet %"] >= 0, "#d62728", "#2ca02c")))
    fig.update_layout(title="Effet de chaque facteur sur cette demi-heure (%)", height=320,
                      yaxis=dict(autorange="reversed"), margin=dict(t=40))
    col2.plotly_chart(fig, use_container_width=True)
    with st.expander("Importance globale des facteurs sur le mois"):
        st.bar_chart(global_importance(models["hybrid"], models["X"]))


# --- Page 3 : risque et planning ------------------------------------------------------------------------
elif page == "Risque et planning":
    st.title(f"Risque et planning - {title_day}")
    fig = go.Figure()
    fig.add_bar(x=iv.index, y=iv["volume_prevu"], name="volume prevu", marker_color="rgba(0,0,0,0.12)",
                yaxis="y2")
    for key, label in (("baseline", "planning actuel"), ("ia", "IA seule"), ("optimise", "IA + risque (recommande)")):
        fig.add_scatter(x=iv.index, y=iv[f"agents_{key}"], name=label, line=dict(shape="hv", width=2.5,
                        color=COLORS[key]))
    fig.update_layout(title="Agents planifies par demi-heure", height=380, margin=dict(t=40),
                      yaxis=dict(title="agents"), yaxis2=dict(title="appels", overlaying="y", side="right"))
    st.plotly_chart(fig, use_container_width=True)

    fig = go.Figure()
    for key, label in (("baseline", "planning actuel"), ("optimise", "planning recommande")):
        fig.add_scatter(x=iv.index, y=100 * iv[f"p_sous_capacite_{key}"], name=label,
                        line=dict(color=COLORS[key], width=2))
    fig.add_hline(y=20, line_dash="dash", line_color="red", annotation_text="seuil eleve")
    fig.add_hline(y=10, line_dash="dot", line_color="orange", annotation_text="seuil moyen")
    fig.update_layout(title="Probabilite de sous-capacite (%)", height=300, margin=dict(t=40))
    st.plotly_chart(fig, use_container_width=True)

    left, right = st.columns(2)
    table = pd.DataFrame({
        "Planning actuel": [d[f"baseline_{k}"] for k in ("cout_agents", "perte_attendue", "VaR95", "ES95", "perte_reelle")],
        "Planning recommande": [d[f"optimise_{k}"] for k in ("cout_agents", "perte_attendue", "VaR95", "ES95", "perte_reelle")],
    }, index=["Cout agents", "Perte attendue (veille)", "VaR 95 %", "Expected Shortfall 95 %", "Perte reelle constatee"])
    left.dataframe(table.map(eur), use_container_width=True)
    left.metric("Service level reel - planning recommande", f"{100 * d['optimise_sl_reel']:.1f} %",
                f"{100 * (d['optimise_sl_reel'] - d['baseline_sl_reel']):+.1f} pts vs actuel")
    fig = go.Figure()
    for key, label in (("baseline", "planning actuel"), ("optimise", "planning recommande")):
        fig.add_histogram(x=losses[f"{key}_{day:%Y%m%d}"], name=label, opacity=0.6, nbinsx=60,
                          marker_color=COLORS[key])
    fig.update_layout(barmode="overlay", title="1 000 scenarios Monte Carlo : perte du jour (EUR)",
                      height=330, margin=dict(t=40))
    right.plotly_chart(fig, use_container_width=True)


# --- Page 4 : what-if ------------------------------------------------------------------------------------
else:
    st.title(f"What-if - {title_day}")
    st.caption("Modifiez une hypothese : la plateforme recalcule le planning optimal et ses consequences.")
    c1, c2, c3, c4 = st.columns(4)
    volume = c1.slider("Variation du volume (%)", -30, 50, 0, 5)
    absence = c2.slider("Absences supplementaires (points)", 0, 30, 0, 5)
    budget = c3.slider("Reduction du budget agents (%)", 0, 30, 0, 5)
    alpha = c4.select_slider("Risque de sous-capacite tolere", options=[0.02, 0.05, 0.10, 0.20], value=0.05,
                             format_func=lambda a: f"{a:.0%}")
    ref = run_what_if(f"{day:%Y-%m-%d}", 1.0, 0.0, 0.0, 0.05)
    sc = run_what_if(f"{day:%Y-%m-%d}", 1 + volume / 100, absence / 100, budget / 100, alpha)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Heures-agents", f"{sc['heures_agents']:.0f}", f"{sc['heures_agents'] - ref['heures_agents']:+.0f}")
    m2.metric("Cout agents", eur(sc["cout_agents"]), eur(sc["cout_agents"] - ref["cout_agents"]),
              delta_color="inverse")
    m3.metric("Perte attendue", eur(sc["perte_attendue"]), eur(sc["perte_attendue"] - ref["perte_attendue"]),
              delta_color="inverse")
    m4.metric("Cout total attendu", eur(sc["cout_total_attendu"]),
              eur(sc["cout_total_attendu"] - ref["cout_total_attendu"]), delta_color="inverse")
    m5.metric("Service level attendu", f"{100 * sc['service_level_attendu']:.1f} %",
              f"{100 * (sc['service_level_attendu'] - ref['service_level_attendu']):+.1f} pts")
    if sc["proba_sous_capacite_max"] >= 0.20:
        st.error(f"Risque eleve : jusqu'a {100 * sc['proba_sous_capacite_max']:.0f} % de probabilite de "
                 f"sous-capacite vers {sc['intervalle_le_plus_risque']:%Hh%M}.")
    if sc["remarque"]:
        st.warning(sc["remarque"])

    fig = go.Figure()
    fig.add_scatter(x=ref["plan"].index, y=ref["plan"], name="reference", line=dict(shape="hv", color="#8c8c8c"))
    fig.add_scatter(x=sc["plan"].index, y=sc["plan"], name="scenario", line=dict(shape="hv", color="#2ca02c", width=3))
    fig.update_layout(title="Planning recommande : reference vs scenario", height=360, margin=dict(t=40))
    st.plotly_chart(fig, use_container_width=True)