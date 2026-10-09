"""What-if (module 16) : tester une hypothese sur la journee planifiee, puis en faire un planning."""
import hashlib
import json
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pandas as pd
from django.contrib import messages
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import Role
from accounts.roles import role_required
from crc.ops.outlook import OFFSETS
from crc.optim.shifts import schedule_shifts, shifts_frame
from crc.optim.staffing import build_curves, deterministic_plan, risk_aware_plan
from crc.optim.whatif import Scenario, what_if
from crc.risk.costs import load_costs
from planning import evaluation
from planning.models import DailyForecast, Decision, PlanInterval, Shift, StaffingPlan
from planning.selectors import forecast_frame, platform_today
from portal.navigation import ALL

PRESETS = [("Volume +20 %", {"volume": 20}), ("10 points d'absences", {"absence": 10}),
           ("Budget agents −15 %", {"budget": 15}), ("Prudence maximale", {"alpha": "0.02"})]


def planned_day() -> date | None:
    today = platform_today()
    day = today + timedelta(days=1) if today else None
    return day if day and DailyForecast.objects.filter(date=day).exists() else None


def read_scenario(data) -> Scenario:
    def number(name, default, lo, hi):
        try:
            return min(max(float(data.get(name, default)), lo), hi)
        except (TypeError, ValueError):
            return default
    return Scenario(volume_factor=1 + number("volume", 0, -50, 100) / 100,
                    extra_absence=number("absence", 0, 0, 50) / 100,
                    budget_cut=number("budget", 0, 0, 50) / 100 or None,
                    alpha=number("alpha", 0.05, 0.01, 0.5))


def describe(s: Scenario) -> str:
    parts = []
    if s.volume_factor != 1:
        parts.append(f"volume {100 * (s.volume_factor - 1):+.0f} %")
    if s.extra_absence:
        parts.append(f"absences +{100 * s.extra_absence:.0f} pts")
    if s.budget_cut:
        parts.append(f"budget agents −{100 * s.budget_cut:.0f} %")
    if s.alpha != 0.05:
        parts.append(f"risque toléré {100 * s.alpha:.0f} %")
    return ", ".join(parts) or "hypothèses de référence"


def run_scenario(day: date, scenario: Scenario) -> dict:
    key = "whatif-" + hashlib.md5(f"{day}-{scenario}-{evaluation.risk_model_key()}".encode()).hexdigest()
    result = cache.get(key)
    if result is None:
        fc = forecast_frame(DailyForecast.objects.get(date=day))
        result = what_if(evaluation.risk_model(day), fc["expected"], fc["aht_expected"], scenario)
        cache.set(key, result, 3600)
    return result


def chart(reference: dict, scenario: dict) -> dict:
    x = [t.strftime("%Y-%m-%dT%H:%M") for t in reference["plan"].index]
    return {"x": x, "reference": reference["plan"].tolist(), "scenario": scenario["plan"].tolist()}


@role_required(*ALL)
def whatif_page(request):
    day = planned_day()
    if day is None:
        return render(request, "planning/empty.html", {"page_title": "What-if"})
    presets = [(label, json.dumps(values)) for label, values in PRESETS]
    return render(request, "planning/whatif.html", {"page_title": "What-if", "day": day, "presets": presets})


@require_POST
@role_required(*ALL)
def whatif_run(request):
    day = planned_day()
    scenario = read_scenario(request.POST)
    reference, result = run_scenario(day, Scenario()), run_scenario(day, scenario)
    delta = {k: result[k] - reference[k] for k in ("heures_agents", "cout_agents", "perte_attendue",
                                                    "cout_total_attendu", "service_level_attendu", "ES95")}
    return render(request, "planning/_whatif_result.html", {
        "day": day, "scenario": scenario, "label": describe(scenario), "ref": reference, "res": result,
        "delta": delta, "chart": chart(reference, result), "post": request.POST,
        "at_capacity": int(result["plan"].max()) >= int(load_costs()["agents_max_available"]),
        "can_convert": request.user.has_role(Role.PLANIFICATEUR, Role.MANAGER) and not scenario.budget_cut})


def build_scenario_plan(day: date, scenario: Scenario, user) -> StaffingPlan:
    """Vacations optimales sous les hypotheses du scenario, evaluees ensuite sur la prevision de
    reference (pour etre comparables aux autres plannings de la journee)."""
    costs = load_costs()
    model = evaluation.risk_model(day)
    stressed = replace(model, absence_rates=np.clip(model.absence_rates + scenario.extra_absence, 0, 0.9))
    forecast = DailyForecast.objects.get(date=day)
    fc = forecast_frame(forecast)
    mu, aht = fc["expected"] * scenario.volume_factor, fc["aht_expected"]
    seed = int(pd.Timestamp(day).strftime("%Y%m%d"))
    center = deterministic_plan(mu, aht, float(stressed.absence_rates.mean()), model.patience, costs)
    curves = build_curves(stressed, mu, aht, center, 100, seed=seed, offsets=OFFSETS)
    need = risk_aware_plan(curves, costs, scenario.alpha)
    solution = schedule_shifts(curves, costs, scenario.alpha)

    plan = StaffingPlan.objects.create(
        date=day, kind=StaffingPlan.Kind.SCENARIO, forecast=forecast, alpha=scenario.alpha, created_by=user,
        title=f"Scénario : {describe(scenario)}",
        scenario={"volume_factor": scenario.volume_factor, "extra_absence": scenario.extra_absence,
                  "alpha": scenario.alpha, "description": describe(scenario)},
        details={"vacations": {"types": int(len(solution.shifts)), "agents": int(solution.shifts["agents"].sum()),
                               "heures_payees": solution.paid_hours, "statut_solveur": solution.status,
                               "ecart_optimum_pct": round(100 * solution.gap, 2),
                               "duree_calcul_s": solution.solve_seconds},
                 "evalue_sur": "prévision de référence"})
    frame = shifts_frame(solution, pd.Timestamp(day))
    Shift.objects.bulk_create([Shift(plan=plan, start=r.debut, end=r.fin, agents=int(r.agents))
                               for r in frame.itertuples()])
    PlanInterval.objects.bulk_create([PlanInterval(plan=plan, ts=ts, agents_required=int(n), agents_scheduled=int(c))
                                      for ts, n, c in zip(fc.index, need, solution.coverage)])
    evaluation.refresh_plan(plan)
    Decision.objects.create(plan=plan, user=user, action=Decision.Action.CREATED,
                            comment=f"Issu du what-if : {describe(scenario)}")
    return plan


@require_POST
@role_required(Role.PLANIFICATEUR, Role.MANAGER)
def whatif_convert(request):
    day = planned_day()
    scenario = read_scenario(request.POST)
    plan = build_scenario_plan(day, scenario, request.user)
    messages.success(request, f"Planning n°{plan.pk} créé à partir du scénario ({describe(scenario)}).")
    response = HttpResponse(status=204)
    response["HX-Redirect"] = f"{reverse('planning')}?jour={day:%Y-%m-%d}&plan={plan.pk}"
    return response
