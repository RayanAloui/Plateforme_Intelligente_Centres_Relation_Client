"""Pages Prevision, Planning et Risque."""
import json
from datetime import date

import numpy as np
import pandas as pd
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import Role
from accounts.roles import role_required
from alerts.models import Alert
from crc.optim.shifts import shift_lengths
from crc.risk.costs import load_costs, observed_losses
from planning import charts, evaluation, exports
from planning.models import DailyForecast, Decision, Shift, StaffingPlan
from planning.selectors import day_navigation, forecast_frame, platform_today, realized, resolve_day
from portal.navigation import ALL

EDITORS = (Role.PLANIFICATEUR, Role.MANAGER)
FACTOR_LABELS = {"heure de la journee": "Heure de la journée", "jour de la semaine": "Jour de la semaine",
                 "saison": "Saison", "jour ferie": "Jour férié", "lendemain de ferie": "Lendemain de férié",
                 "vacances scolaires": "Vacances scolaires", "campagne commerciale": "Campagne commerciale"}


def _empty(request, title):
    return render(request, "planning/empty.html", {"page_title": title})


def _url(name, day, **params):
    query = "&".join([f"jour={day:%Y-%m-%d}", *[f"{k}={v}" for k, v in params.items()]])
    return f"{reverse(name)}?{query}"


# --- Prevision -------------------------------------------------------------------------------------------
def explanation_context(forecast: DailyForecast, hhmm: str | None) -> dict:
    intervals = list(forecast.intervals.order_by("ts"))
    chosen = next((i for i in intervals if i.ts.strftime("%H:%M") == hhmm), None) \
        or max(intervals, key=lambda i: i.expected)
    effects = sorted(chosen.explanation.items(), key=lambda kv: -abs(kv[1]))
    scale = max([abs(v) for _, v in effects] + [1])
    return {"interval": chosen, "times": [i.ts.strftime("%H:%M") for i in intervals],
            "effects": [{"facteur": FACTOR_LABELS.get(k, k), "effet": v, "largeur": round(100 * abs(v) / scale)}
                        for k, v in effects],
            "average_slot": forecast.level_total / len(intervals) if forecast.level_total else None,
            "forecast": forecast}


@role_required(*ALL)
def forecast_page(request):
    day = resolve_day(request)
    if day is None:
        return _empty(request, "Prévision")
    forecast = DailyForecast.objects.select_related("model_version").get(date=day)
    fc = forecast_frame(forecast)
    real = realized(day)
    anomalies = list(Alert.objects.filter(date=day, source=Alert.Source.ANOMALY).order_by("start"))
    peak = fc["expected"].idxmax()
    context = {
        "page_title": "Prévision", "nav": day_navigation(day), "forecast": forecast,
        "peak_time": peak, "peak_value": fc.loc[peak, "expected"],
        "aht": float(np.average(fc["aht_expected"], weights=fc["expected"])),
        "chart": charts.forecast_chart(fc, real, anomalies), "anomalies": anomalies,
        **explanation_context(forecast, request.GET.get("heure")),
    }
    if real is not None:
        actual = real["offered"].sum()
        inside = ((real["offered"] >= fc["q10"]) & (real["offered"] <= fc["q90"])).mean()
        context.update({"actual_total": actual, "error_pct": 100 * (forecast.total_expected - actual) / actual,
                        "coverage80": 100 * inside})
    return render(request, "planning/forecast.html", context)


@role_required(*ALL)
def forecast_explain(request):
    forecast = get_object_or_404(DailyForecast, date=date.fromisoformat(request.GET["jour"]))
    return render(request, "planning/_explanation.html", explanation_context(forecast, request.GET.get("heure")))


# --- Planning ---------------------------------------------------------------------------------------------
def plan_context(request, plan: StaffingPlan) -> dict:
    fc = forecast_frame(plan.forecast)
    user = request.user
    actions = [(a, label) for a, label in (("soumettre", "Soumettre à validation"), ("valider", "Valider"),
                                           ("publier", "Publier"), ("refuser", "Refuser"))
               if plan.can(a, user)]
    costs = load_costs()
    return {
        "plan": plan, "plan_chart": charts.plan_chart(plan, fc), "gantt": charts.gantt_chart(plan),
        "actions": actions, "decisions": plan.decisions.select_related("user"),
        "editable": plan.is_editable and user.has_role(*EDITORS) and plan.kind != StaffingPlan.Kind.CURRENT,
        "can_adjust": user.has_role(*EDITORS) and plan.shifts.exists(),
        "shifts": plan.shifts.order_by("start", "end"),
        "lengths": shift_lengths(costs), "hours": [f"{h:02d}:00" for h in range(24)],
        "under_count": sum(1 for r in plan.intervals.all() if r.gap < 0),
    }


@role_required(*ALL)
def planning_page(request):
    day = resolve_day(request)
    if day is None:
        return _empty(request, "Planning")
    plans = list(StaffingPlan.objects.filter(date=day).order_by("created_at"))
    wanted = request.GET.get("plan")
    plan = next((p for p in plans if str(p.pk) == wanted), None) or \
        next((p for p in plans if p.kind == "recommande" and p.status != "remplace"), None) or plans[0]
    return render(request, "planning/planning.html", {
        "page_title": "Planning", "nav": day_navigation(day), "plans": plans, **plan_context(request, plan)})


def _panel(request, plan, note=None):
    response = render(request, "planning/_plan_panel.html", {**plan_context(request, plan), "note": note})
    return response


def _redirect(plan):
    response = HttpResponse(status=204)
    response["HX-Redirect"] = _url("planning", plan.date, plan=plan.pk)
    return response


@require_POST
@role_required(*ALL)
def plan_transition(request, pk, action):
    plan = get_object_or_404(StaffingPlan, pk=pk)
    try:
        plan.transition(action, request.user, request.POST.get("comment", "").strip())
        labels = {"soumettre": "soumis à validation", "valider": "validé", "publier": "publié",
                  "refuser": "renvoyé en brouillon"}
        messages.success(request, f"Planning n°{plan.pk} {labels[action]}.")
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    return _redirect(plan)


@require_POST
@role_required(*EDITORS)
def plan_adjust(request, pk):
    plan = get_object_or_404(StaffingPlan, pk=pk)
    copy = evaluation.copy_plan(plan, request.user)
    messages.success(request, f"Brouillon n°{copy.pk} créé : vous pouvez ajuster ses vacations.")
    return _redirect(copy)


def _editable(request, pk) -> StaffingPlan:
    """Planning verrouille pour la duree de la modification (a appeler dans une transaction)."""
    plan = get_object_or_404(StaffingPlan.objects.select_for_update(), pk=pk)
    today = platform_today()
    if not plan.is_editable or plan.kind == StaffingPlan.Kind.CURRENT or (today and plan.date <= today):
        raise PermissionDenied("Seul le brouillon d'une journee a venir peut etre modifie.")
    return plan


def _after_edit(request, plan, what):
    evaluation.refresh_plan(plan)
    Decision.objects.create(plan=plan, user=request.user, action=Decision.Action.ADJUSTED, comment=what)
    return _panel(request, plan, note=f"{what} — couverture et risque recalculés.")


@require_POST
@role_required(*EDITORS)
@transaction.atomic
def shift_change(request, pk, shift_id, delta):
    plan = _editable(request, pk)
    shift = get_object_or_404(Shift, pk=shift_id, plan=plan)
    shift.agents = max(0, shift.agents + delta)
    label = f"Vacation {shift.start:%Hh}–{shift.end:%Hh} : {'+' if delta > 0 else '−'}1 agent"
    if shift.agents == 0:
        shift.delete()
    else:
        shift.save()
    return _after_edit(request, plan, label)


@require_POST
@role_required(*EDITORS)
@transaction.atomic
def shift_add(request, pk):
    plan = _editable(request, pk)
    try:
        start = pd.Timestamp(f"{plan.date:%Y-%m-%d} {request.POST['debut']}")
        hours, agents = int(request.POST["duree"]), int(request.POST["agents"])
        if hours not in shift_lengths(load_costs()) or not 1 <= agents <= 60:
            raise ValueError
    except (KeyError, ValueError):
        return _panel(request, plan, note="Vacation invalide : vérifiez l'heure, la durée et le nombre d'agents.")
    Shift.objects.create(plan=plan, start=start, end=start + pd.Timedelta(hours=hours), agents=agents)
    return _after_edit(request, plan, f"Vacation ajoutée : {agents} agent(s), {start:%Hh}–"
                                      f"{start + pd.Timedelta(hours=hours):%Hh}")


@role_required(*ALL)
def plan_export(request, pk, fmt):
    plan = get_object_or_404(StaffingPlan, pk=pk)
    name = f"planning_{plan.date:%Y%m%d}_n{plan.pk}"
    if fmt == "xlsx":
        content, mime = exports.excel_plan(plan), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        content, mime = exports.pdf_plan(plan), "application/pdf"
    Decision.objects.create(plan=plan, user=request.user, action=Decision.Action.EXPORTED, comment=fmt.upper())
    response = HttpResponse(content, content_type=mime)
    response["Content-Disposition"] = f'attachment; filename="{name}.{fmt}"'
    return response


# --- Risque ---------------------------------------------------------------------------------------------
def var_reliability() -> dict:
    """Depuis le debut de l'exploitation : la VaR 95 % du planning en vigueur a-t-elle tenu ?"""
    today = platform_today()
    rows = []
    for plan in StaffingPlan.objects.filter(status=StaffingPlan.Status.PUBLISHED, date__lte=today,
                                            var95__isnull=False):
        real = realized(plan.date)
        if real is not None:
            loss = observed_losses(real, load_costs())["perte"].sum()
            rows.append((plan.date, loss, plan.var95))
    exceed = sum(1 for _, loss, v in rows if loss > v)
    return {"days": len(rows), "exceedances": exceed,
            "rate": 100 * exceed / len(rows) if rows else None}


@role_required(*ALL)
def risk_page(request):
    day = resolve_day(request)
    if day is None:
        return _empty(request, "Risque")
    plans = list(StaffingPlan.objects.filter(date=day).exclude(status=StaffingPlan.Status.SUPERSEDED)
                 .order_by("created_at"))
    shown = plans[:4]
    losses = {f"{p.get_kind_display()} (n°{p.pk})": (charts.PLAN_COLORS.get(p.kind), evaluation.loss_scenarios(p))
              for p in shown}
    real = realized(day)
    realized_loss, percentile = None, None
    if real is not None:
        realized_loss = float(observed_losses(real, load_costs())["perte"].sum())
        in_force = next((p for p in plans if p.status == StaffingPlan.Status.PUBLISHED), None)
        if in_force:
            sims = evaluation.loss_scenarios(in_force)
            percentile = 100 * float((sims < realized_loss).mean())
    return render(request, "planning/risk.html", {
        "page_title": "Risque", "nav": day_navigation(day), "plans": plans,
        "compare_chart": charts.risk_compare_chart(shown), "loss_chart": charts.loss_chart(losses, realized_loss),
        "realized_loss": realized_loss, "percentile": percentile, "reliability": var_reliability(),
    })
