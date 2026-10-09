"""Donnees des graphiques (Plotly.js), preparees cote serveur en listes simples."""
import numpy as np
import pandas as pd

from planning.models import StaffingPlan

PLAN_COLORS = {"actuel": "#94a3b8", "ia": "#3b82f6", "recommande": "#16a34a", "ajuste": "#9333ea",
               "scenario": "#f59e0b"}


def _iso(index) -> list[str]:
    return [pd.Timestamp(t).strftime("%Y-%m-%dT%H:%M") for t in index]


def forecast_chart(fc: pd.DataFrame, realized: pd.DataFrame | None, anomalies: list) -> dict:
    data = {"x": _iso(fc.index), "attendu": fc["expected"].round(1).tolist(),
            "q01": fc["q01"].tolist(), "q10": fc["q10"].tolist(), "q90": fc["q90"].tolist(),
            "q99": fc["q99"].tolist()}
    if realized is not None:
        data["observe"] = realized["offered"].reindex(fc.index).tolist()
    data["anomalies"] = [{"x": a.start.strftime("%Y-%m-%dT%H:%M"), "x1": a.end.strftime("%Y-%m-%dT%H:%M"),
                          "niveau": a.level} for a in anomalies]
    return data


def plan_chart(plan: StaffingPlan, fc: pd.DataFrame) -> dict:
    rows = list(plan.intervals.order_by("ts").values("ts", "agents_required", "agents_scheduled",
                                                      "undercap_probability"))
    return {"x": _iso([r["ts"] for r in rows]),
            "besoin": [r["agents_required"] for r in rows],
            "planifies": [r["agents_scheduled"] for r in rows],
            "risque": [round(100 * (r["undercap_probability"] or 0), 1) for r in rows],
            "volume": fc["expected"].reindex([r["ts"] for r in rows]).round(0).tolist(),
            "couleur": PLAN_COLORS.get(plan.kind, "#16a34a")}


def gantt_chart(plan: StaffingPlan) -> dict:
    shifts = list(plan.shifts.order_by("start", "end"))
    return {"debut": [s.start.strftime("%Y-%m-%dT%H:%M") for s in shifts],
            "duree_ms": [int((s.end - s.start).total_seconds() * 1000) for s in shifts],
            "libelle": [f"{s.agents} agent{'s' if s.agents > 1 else ''} · {s.start:%Hh}–{s.end:%Hh}" for s in shifts],
            "agents": [s.agents for s in shifts]}


def risk_compare_chart(plans: list[StaffingPlan]) -> dict:
    series = []
    for p in plans:
        rows = list(p.intervals.order_by("ts").values("ts", "undercap_probability"))
        series.append({"nom": f"{p.get_kind_display()} (n°{p.pk})", "couleur": PLAN_COLORS.get(p.kind),
                       "x": _iso([r["ts"] for r in rows]),
                       "y": [round(100 * (r["undercap_probability"] or 0), 1) for r in rows]})
    return {"series": series}


def loss_chart(losses: dict, realized_loss: float | None) -> dict:
    """losses : {nom: (couleur, tableau des pertes simulees)}"""
    out = {"series": [], "reel": realized_loss}
    for name, (color, values) in losses.items():
        out["series"].append({"nom": name, "couleur": color, "valeurs": np.round(values, 0).tolist(),
                              "var95": float(np.quantile(values, 0.95))})
    return out
