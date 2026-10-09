"""Suivi des modeles (MLOps) : performance en exploitation, derive, versions, reentrainement."""
from datetime import timedelta

import numpy as np
import pandas as pd
from django.contrib import messages
from django.db import connection
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from accounts.models import Role
from accounts.roles import role_required
from planning import services
from planning.models import IntervalForecast, ModelVersion, PipelineRun, PlatformState
from planning.tasks import launch, running_run

RECENT_DAYS = 7


def live_performance(days: int = 60) -> pd.DataFrame:
    """Pour chaque journee realisee : erreur de la prevision emise la veille, demi-heure par demi-heure."""
    today = PlatformState.get().current_date
    if today is None:
        return pd.DataFrame()
    rows = IntervalForecast.objects.filter(forecast__date__lte=today, forecast__date__gt=today - timedelta(days=days)) \
        .values("ts", "expected", "q10", "q90", "forecast__date", "forecast__model_version__version")
    fc = pd.DataFrame(list(rows))
    if fc.empty:
        return fc
    with connection.cursor() as cur:
        cur.execute("SELECT ts, offered, is_imputed FROM core.interval_metrics WHERE ts >= %s AND ts < %s",
                    [fc["ts"].min(), fc["ts"].max() + timedelta(minutes=30)])
        actual = pd.DataFrame(cur.fetchall(), columns=["ts", "offered", "is_imputed"])
    df = fc.merge(actual, on="ts")
    df = df[~df["is_imputed"]]
    df["offered"] = df["offered"].astype(float)
    out = df.groupby("forecast__date").apply(lambda g: pd.Series({
        "wape": 100 * (g["expected"] - g["offered"]).abs().sum() / g["offered"].sum(),
        "biais": 100 * (g["expected"] - g["offered"]).sum() / g["offered"].sum(),
        "couverture80": 100 * ((g["offered"] >= g["q10"]) & (g["offered"] <= g["q90"])).mean(),
        "version": g["forecast__model_version__version"].iloc[0],
    }), include_groups=False)
    out.index.name = "date"
    return out


def drift_status(perf: pd.DataFrame, reference: dict) -> dict:
    """Compare les 7 dernieres journees a la performance hors echantillon annoncee par la fiche du modele."""
    if len(perf) < 3:
        return {"level": "inconnu", "title": "Pas encore assez de recul",
                "text": "Le suivi démarre après trois journées réalisées."}
    recent = perf.tail(RECENT_DAYS)
    wape, bias, cover = recent["wape"].mean(), recent["biais"].mean(), recent["couverture80"].mean()
    ref = reference.get("WAPE_%") or 15.0
    facts = {"wape": wape, "biais": bias, "couverture": cover, "reference": ref}
    if wape > 1.3 * ref or abs(bias) > 5 or cover < 65:
        return {"level": "derive", "title": "Dérive détectée : réentraînement conseillé", **facts,
                "text": "Sur les dernières journées, la prévision s'écarte nettement de sa performance de référence."}
    if wape > 1.15 * ref or abs(bias) > 3 or cover < 72:
        return {"level": "surveiller", "title": "À surveiller", **facts,
                "text": "Légère dégradation : rien d'alarmant, mais à suivre dans les prochains jours."}
    return {"level": "ok", "title": "Modèle en bonne santé", **facts,
            "text": "La performance en exploitation est conforme à celle mesurée hors échantillon."}


def readable_metrics(version: ModelVersion | None) -> dict:
    m = version.metrics if version else {}
    return {"wape": m.get("WAPE_%"), "biais": m.get("biais_%"), "couverture": m.get("couverture_fourchette_80_%"),
            "periode": m.get("periode")}


@role_required(Role.ADMINISTRATEUR)
def models_page(request):
    active = ModelVersion.objects.filter(is_active=True).first()
    perf = live_performance()
    chart = {"x": [d.isoformat() for d in perf.index], "wape": perf["wape"].round(2).tolist() if len(perf) else [],
             "biais": perf["biais"].round(2).tolist() if len(perf) else [],
             "reference": (active.metrics.get("WAPE_%") if active else None)}
    return render(request, "administration/models.html", {
        "page_title": "Modèles", "active": active, "metrics": readable_metrics(active),
        "versions": [(v, readable_metrics(v)) for v in ModelVersion.objects.all()],
        "days_monitored": len(perf),
        "drift": drift_status(perf, active.metrics if active else {}), "chart": chart,
        "runs": PipelineRun.objects.select_related("triggered_by")[:15], "running": running_run(),
        "uncertainty": (active.card or {}).get("incertitude", {}) if active else {}})


def _launch(request, kind, func):
    run = launch(kind, request.user, func)
    return render(request, "planning/_cycle_status.html", {"run": run or running_run(), "already": run is None})


@require_POST
@role_required(Role.ADMINISTRATEUR)
def model_retrain(request):
    return _launch(request, PipelineRun.Kind.RETRAIN, services.retrain_and_replan)


@require_POST
@role_required(Role.ADMINISTRATEUR)
def replan(request):
    return _launch(request, PipelineRun.Kind.REPLAN, services.replan_tomorrow)


@require_POST
@role_required(Role.ADMINISTRATEUR)
def model_activate(request, pk):
    version = get_object_or_404(ModelVersion, pk=pk)
    version.activate()
    messages.success(request, f"Version {version.version} activée. Replanifiez demain pour l'utiliser tout de suite.")
    response = render(request, "planning/_cycle_status.html", {"run": None})
    response["HX-Refresh"] = "true"
    return response
