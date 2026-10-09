"""Historique (prevu vs realise) et Capacite (recrutement et budget a long terme)."""
from datetime import timedelta

import numpy as np
import pandas as pd
from django.core.cache import cache
from django.db import connection
from django.db.models import Count, Q, Sum
from django.shortcuts import render

from accounts.roles import role_required
from alerts.models import Alert
from crc.datasets import load_history
from crc.ops import capacity
from crc.optim.staffing import evaluate_plan
from crc.risk.costs import load_costs
from planning import evaluation
from planning.models import DailyForecast, StaffingPlan
from planning.selectors import platform_today
from portal.navigation import ALL

COUNTERFACTUAL_NOTE = ("Les données réalisées sont produites avec le planning de l'outil en place. L'effet d'un autre "
                       "planning est donc évalué face à la demande et aux absences réelles avec le même moteur "
                       "(Erlang A), comme dans l'expérience finale du projet.")


def realized_days(first, last) -> pd.DataFrame:
    with connection.cursor() as cur:
        cur.execute("""SELECT ts, offered, avg_handle_seconds, agents_scheduled, agents_absent
                       FROM core.interval_metrics WHERE ts >= %s AND ts < %s ORDER BY ts""",
                    [first, last + timedelta(days=1)])
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["ts", "offered", "aht", "scheduled", "absent"]).set_index("ts").astype(float)
    df["date"] = df.index.date
    return df


def plan_agents(plan: StaffingPlan) -> np.ndarray:
    return np.array(list(plan.intervals.order_by("ts").values_list("agents_scheduled", flat=True)))


@role_required(*ALL)
def history_page(request):
    today = platform_today()
    forecasts = list(DailyForecast.objects.filter(date__lte=today).order_by("-date")) if today else []
    if not forecasts:
        return render(request, "planning/history.html", {"page_title": "Historique", "rows": []})
    real = realized_days(forecasts[-1].date, forecasts[0].date)
    costs = load_costs()
    patience = evaluation.risk_model().patience
    alerts = dict(Alert.objects.filter(date__lte=today).values_list("date").annotate(n=Count("id")))
    rows = []
    for fc in forecasts:
        day = real[real["date"] == fc.date]
        if len(day) != 48:
            continue
        plans = {p.kind: p for p in StaffingPlan.objects.filter(date=fc.date).order_by("created_at")}
        in_force = StaffingPlan.objects.filter(date=fc.date, status=StaffingPlan.Status.PUBLISHED).first() \
            or plans.get("actuel")
        absence = (day["absent"].sum() / day["scheduled"].sum())
        outcome = {}
        for key, plan in (("wfm", plans.get("actuel")), ("vigueur", in_force), ("recommande", plans.get("recommande"))):
            if plan is None:
                continue
            e = evaluate_plan(plan_agents(plan), day["offered"], day["aht"], pd.Series(absence, index=day.index),
                              patience, costs)
            outcome[key] = {"total": float(e["cout_agents"].sum() + e["perte"].sum()), "perte": float(e["perte"].sum()),
                            "sl": float((e["sl"] * e["appels"]).sum() / max(e["appels"].sum(), 1))}
        actual = day["offered"].sum()
        decisions = in_force.decisions.filter(user__isnull=False).count() if in_force else 0
        rows.append({
            "date": fc.date, "prevu": fc.total_expected, "reel": actual,
            "ecart": 100 * (fc.total_expected - actual) / actual,
            "dans_fourchette": fc.total_q10 <= actual <= fc.total_q90 if fc.total_q10 else None,
            "plan": in_force, "outcome": outcome, "alertes": alerts.get(fc.date, 0), "decisions": decisions,
            "gain": outcome["wfm"]["total"] - outcome["vigueur"]["total"] if {"wfm", "vigueur"} <= set(outcome) else 0.0,
            "potentiel": outcome["wfm"]["total"] - outcome["recommande"]["total"]
            if {"wfm", "recommande"} <= set(outcome) else 0.0,
        })
    team = [r for r in rows if r["plan"] and r["plan"].kind != StaffingPlan.Kind.CURRENT]
    summary = {
        "days": len(rows), "wape": float(np.mean([abs(r["ecart"]) for r in rows])) if rows else None,
        "in_range": 100 * np.mean([r["dans_fourchette"] for r in rows if r["dans_fourchette"] is not None]) if rows else None,
        "team_days": len(team), "gain": sum(r["gain"] for r in rows),
        "potential": sum(r["potentiel"] for r in rows),
    }
    chart = {"x": [r["date"].isoformat() for r in reversed(rows)],
             "prevu": [round(r["prevu"]) for r in reversed(rows)], "reel": [int(r["reel"]) for r in reversed(rows)],
             "gain": list(np.cumsum([round(r["gain"]) for r in reversed(rows)]).tolist()),
             "potentiel": list(np.cumsum([round(r["potentiel"]) for r in reversed(rows)]).tolist())}
    return render(request, "planning/history.html", {"page_title": "Historique", "rows": rows, "summary": summary,
                                                     "chart": chart, "note": COUNTERFACTUAL_NOTE})


# --- Capacite -------------------------------------------------------------------------------------------
def hours_per_call(history: pd.DataFrame) -> tuple[float, str]:
    """Heures d'agents par appel des plannings recommandes recents (sinon, du planning historique)."""
    recent = StaffingPlan.objects.filter(kind=StaffingPlan.Kind.RECOMMENDED).order_by("-date")[:30]
    totals = recent.aggregate(h=Sum("agent_hours"), c=Sum("forecast__total_expected"))
    if totals["h"] and totals["c"]:
        return totals["h"] / totals["c"], f"plannings recommandés des {recent.count()} dernières journées"
    return capacity.staffing_ratio(history), "planning de l'outil en place sur les 12 derniers mois"


def capacity_data(horizon: int) -> dict:
    key = f"capacite-{platform_today()}-{horizon}"
    data = cache.get(key)
    if data is None:
        history = load_history()
        monthly = capacity.monthly_series(history)
        forecast = capacity.forecast_months(monthly, horizon)
        ratio, ratio_source = hours_per_call(history)
        recent = history[history.index >= history.index[-1] - pd.Timedelta(days=365)]
        absence = float(recent["agents_absent"].sum() / recent["agents_scheduled"].sum())
        plan = capacity.capacity_plan(forecast, ratio, absence, load_costs()["cost_agent_hour"])
        data = {"monthly": monthly, "plan": plan, "reliability": capacity.backtest(monthly),
                "ratio": ratio, "ratio_source": ratio_source, "absence": absence}
        cache.set(key, data, 6 * 3600)
    return data


@role_required(*ALL)
def capacity_page(request):
    try:
        horizon = int(request.GET.get("horizon", 24))
    except ValueError:
        horizon = 24
    horizon = horizon if horizon in (12, 24, 36, 48) else 24
    data = capacity_data(horizon)
    plan, monthly = data["plan"], data["monthly"]
    months = [{"mois": m, **row} for m, row in plan.to_dict("index").items()]
    chart = {"hist_x": [m.strftime("%Y-%m-%d") for m in monthly.index], "hist": monthly["total"].round().tolist(),
             "x": [m.strftime("%Y-%m-%d") for m in plan.index],
             **{c: plan[c].round().tolist() for c in ("p025", "p10", "p50", "p90", "p975",
                                                       "etp_p10", "etp_p50", "etp_p90")}}
    last_year = plan.iloc[-12:] if len(plan) >= 12 else plan
    return render(request, "planning/capacity.html", {
        "page_title": "Capacité et recrutement", "horizon": horizon, "months": months, "chart": chart,
        "reliability": data["reliability"].reset_index().to_dict("records"), "ratio": data["ratio"],
        "ratio_source": data["ratio_source"], "absence": data["absence"],
        "current_fte": float(plan["etp_p50"].iloc[0]), "final_fte": float(last_year["etp_p50"].mean()),
        "final_fte_high": float(last_year["etp_p90"].mean()),
        "budget_year": float(last_year["budget_p50"].sum()), "budget_year_high": float(last_year["budget_p90"].sum()),
        "far_horizon": horizon > 24, "first_month": plan.index[0], "last_month": plan.index[-1],
        "horizons": [(12, "1 an"), (24, "2 ans"), (36, "3 ans"), (48, "4 ans")],
        "fte_hours": capacity.PAID_HOURS_PER_FTE})
