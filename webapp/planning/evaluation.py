"""Re-evaluation d'un planning modifie a la main : couverture, risque, synthese.

Quand un planificateur ajoute ou retire des agents, la plateforme recalcule aussitot la
couverture et le risque du planning, avec le meme moteur Monte Carlo que le cycle quotidien.
"""
from datetime import date

import numpy as np
import pandas as pd
from django.core.cache import cache
from django.db import transaction

from crc.ops.outlook import evaluate_plan, risk_model_for
from crc.risk.costs import load_costs
from crc.risk.simulation import OperationalRiskModel
from planning import services
from planning.models import Decision, PlanInterval, Shift, StaffingPlan
from planning.selectors import forecast_frame, platform_today

_MODELS: dict = {}


def remember_model(version: str, day: date, model: OperationalRiskModel) -> None:
    """Le cycle quotidien depose ici le modele qu'il vient de construire : les ajustements
    du lendemain sont alors recalcules instantanement."""
    _MODELS.clear()
    _MODELS[(version, day)] = model


def risk_model(day: date | None = None) -> OperationalRiskModel:
    """Modele de risque de la journee planifiee, mis en cache."""
    version, bundle = services.active_bundle()
    today = platform_today()
    key = (version.version, day or (today + pd.Timedelta(days=1) if today else None))
    if key not in _MODELS:
        history, _, costs = services.engine_inputs()
        remember_model(*key, risk_model_for(bundle, history, costs))
    model = _MODELS[key]
    model.costs = load_costs()          # les parametres peuvent changer depuis l'interface
    return model


def plan_forecast(plan: StaffingPlan) -> pd.DataFrame:
    fc = forecast_frame(plan.forecast)
    return fc.rename(columns={"expected": "attendu", "aht_expected": "aht"})


def coverage_from_shifts(shifts, day: date) -> pd.Series:
    """Agents presents par demi-heure (journee cyclique, comme le modele de vacations)."""
    idx = pd.date_range(pd.Timestamp(day), periods=48, freq="30min")
    cover = np.zeros(48, dtype=int)
    for s in shifts:
        start = int((pd.Timestamp(s.start) - idx[0]) / pd.Timedelta(minutes=30))
        for k in range(int(round(s.hours * 2))):
            cover[(start + k) % 48] += s.agents
    return pd.Series(cover, index=idx)


def seed_for(plan: StaffingPlan) -> int:
    return int(pd.Timestamp(plan.date).strftime("%Y%m%d"))


@transaction.atomic
def refresh_plan(plan: StaffingPlan) -> StaffingPlan:
    """Couverture et risque recalcules a partir des vacations du planning."""
    fc = plan_forecast(plan)
    agents = coverage_from_shifts(plan.shifts.all(), plan.date).reindex(fc.index).fillna(0).astype(int)
    outlook = evaluate_plan(risk_model(plan.date), fc, agents.to_numpy(), seed_for(plan))
    PlanInterval.objects.bulk_update(_updated_rows(plan, outlook),
                                     ["agents_scheduled", "undercap_probability", "expected_loss",
                                      "expected_service_level"])
    for field, value in outlook.summary.items():
        setattr(plan, field, value)
    # On n'enregistre que la synthese : jamais le statut, qui peut avoir change entre-temps.
    plan.save(update_fields=[*outlook.summary, "updated_at"])
    return plan


def _updated_rows(plan, outlook):
    rows = list(plan.intervals.all())
    for row in rows:
        ts = pd.Timestamp(row.ts)
        row.agents_scheduled = int(outlook.agents[ts])
        row.undercap_probability = float(outlook.undercap[ts])
        row.expected_loss = float(outlook.expected_loss[ts])
        row.expected_service_level = float(outlook.service_level[ts])
    return rows


@transaction.atomic
def copy_plan(plan: StaffingPlan, user, kind: str = StaffingPlan.Kind.ADJUSTED, title: str = "") -> StaffingPlan:
    """Nouveau brouillon, copie conforme d'un planning (vacations et lignes), pour l'ajuster."""
    new = StaffingPlan.objects.create(
        date=plan.date, kind=kind, status=StaffingPlan.Status.DRAFT, parent=plan, forecast=plan.forecast,
        alpha=plan.alpha, title=title or f"Ajustement du planning n°{plan.pk}", created_by=user,
        details=plan.details, **{f: getattr(plan, f) for f in (
            "agent_hours", "cost_agents", "expected_loss", "var95", "es95", "expected_service_level",
            "max_undercap_probability")})
    Shift.objects.bulk_create([Shift(plan=new, start=s.start, end=s.end, agents=s.agents) for s in plan.shifts.all()])
    PlanInterval.objects.bulk_create([PlanInterval(
        plan=new, ts=r.ts, agents_required=r.agents_required, agents_scheduled=r.agents_scheduled,
        undercap_probability=r.undercap_probability, expected_loss=r.expected_loss,
        expected_service_level=r.expected_service_level) for r in plan.intervals.all()])
    Decision.objects.create(plan=new, user=user, action=Decision.Action.CREATED,
                            comment=f"Copie du planning n°{plan.pk} pour ajustement")
    return new


def loss_scenarios(plan: StaffingPlan, n: int = 1000) -> np.ndarray:
    """Pertes simulees de la journee pour ce planning (mises en cache)."""
    key = f"pertes-{plan.pk}-{plan.updated_at:%Y%m%d%H%M%S%f}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    fc = plan_forecast(plan)
    agents = np.array(list(plan.intervals.order_by("ts").values_list("agents_scheduled", flat=True)))
    sim = risk_model(plan.date).simulate(fc["attendu"], fc["aht"], agents, n=n, seed=seed_for(plan))
    losses = sim["perte"].sum(axis=1)
    cache.set(key, losses, 3600)
    return losses
