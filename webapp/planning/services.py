"""Services de la plateforme : le pont entre Django et le moteur crc.

    train_model        entraine, sauvegarde et active une version du modele de prevision
    plan_next_day      prevision, plannings (actuel vs recommande), risque et alertes du lendemain
    run_daily_cycle    le cycle complet : exports -> import -> anomalies -> (reentrainement) -> lendemain
"""
import time
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from django.db import transaction

from alerts.models import Alert
from crc.app.alerts import message as alert_message
from crc.datasets import load_history
from crc.db import read_sql
from crc.forecasting.features import build_features
from crc.forecasting.intervals import rolling_forecast
from crc.forecasting.registry import build_bundle, load_bundle, save_bundle
from crc.ops import simulator
from crc.ops.ingest import import_day, record_events
from crc.ops.outlook import compute_outlook, detect_anomalies
from crc.risk.costs import load_costs
from crc.optim.shifts import shifts_frame
from planning.models import (DailyForecast, Decision, IntervalForecast, ModelVersion, PipelineRun,
                             PlanInterval, PlatformState, Shift, StaffingPlan)

LEVELS = {"Moyen": Alert.Level.MEDIUM, "Eleve": Alert.Level.HIGH}
_BUNDLES: dict = {}


# --- Journal des etapes ------------------------------------------------------------------------------
@contextmanager
def step(run: PipelineRun | None, label: str):
    """Enregistre une etape du traitement (statut, duree, details) dans le journal du run."""
    entry = {"etape": label, "statut": "en_cours"}
    started = time.perf_counter()
    if run:
        run.steps = [*run.steps, entry]
        run.save(update_fields=["steps"])
    try:
        yield entry
        entry["statut"] = "ok"
    except Exception:
        entry["statut"] = "echec"
        raise
    finally:
        entry["duree_s"] = round(time.perf_counter() - started, 1)
        if run:
            run.save(update_fields=["steps"])


# --- Donnees du moteur -----------------------------------------------------------------------------------
def engine_inputs():
    history = load_history()
    events = read_sql("SELECT * FROM ref.events")
    return history, events, load_costs()


def active_bundle():
    version = ModelVersion.objects.filter(is_active=True).first()
    if version is None:
        raise RuntimeError("Aucun modele actif : lancer  python webapp/manage.py init_platform")
    if version.version not in _BUNDLES:
        _BUNDLES[version.version] = load_bundle(version.version)
    return version, _BUNDLES[version.version]


def train_model(cutoff: date, run: PipelineRun | None = None) -> ModelVersion:
    """Champion reentraine sur tout l'historique anterieur a `cutoff`, incertitude recalibree
    sur 12 mois de previsions hors echantillon, puis enregistre et active."""
    history, events, _ = engine_inputs()
    X = build_features(history, events)
    cut = pd.Timestamp(cutoff)
    rolling = rolling_forecast(history, events, X, cut - pd.DateOffset(months=12), cut)
    bundle = build_bundle(history, events, X, cut, rolling)
    path = save_bundle(bundle)
    version, _ = ModelVersion.objects.update_or_create(version=bundle.version, defaults={
        "cutoff": cutoff, "file_path": str(path), "card": bundle.card,
        "metrics": bundle.card["performances_hors_echantillon"]})
    version.activate()
    _BUNDLES.pop(version.version, None)
    return version


# --- Le lendemain ------------------------------------------------------------------------------------
@transaction.atomic
def persist_outlook(outlook, run, model_version) -> dict:
    day, fc = outlook.day, outlook.forecast
    forecast, _ = DailyForecast.objects.update_or_create(date=day, defaults={
        "model_version": model_version, "run": run, "total_expected": float(fc["attendu"].sum()),
        "total_q10": float(fc["total_q10"].iloc[0]), "total_q90": float(fc["total_q90"].iloc[0]),
        "level_total": float(fc["niveau_jour"].iloc[0])})
    effect_cols = [c for c in fc.columns if c.startswith("effet:")]
    forecast.intervals.all().delete()
    IntervalForecast.objects.bulk_create([
        IntervalForecast(forecast=forecast, ts=ts, expected=r["attendu"], q01=r["q01"], q10=r["q10"],
                         q50=r["q50"], q90=r["q90"], q99=r["q99"], aht_expected=r["aht"],
                         explanation={c.removeprefix("effet:"): round(float(r[c]), 1) for c in effect_cols})
        for ts, r in fc.iterrows()])

    # On remplace les plannings automatiques precedents, jamais ceux qu'un utilisateur a touches.
    auto = StaffingPlan.objects.filter(date=day, kind__in=["actuel", "recommande"]).exclude(
        decisions__user__isnull=False)
    Alert.objects.filter(date=day, source=Alert.Source.RISK, status=Alert.Status.NEW).delete()
    auto.delete()

    need = outlook.ideal.agents
    # Le planning de l'outil WFM est celui en vigueur, sauf si un planning a deja ete publie a la main.
    in_force = StaffingPlan.Status.SUPERSEDED if StaffingPlan.objects.filter(
        date=day, status=StaffingPlan.Status.PUBLISHED).exists() else StaffingPlan.Status.PUBLISHED
    plans = {}
    for kind, status, title in (("actuel", in_force, "Planning de l'outil WFM en place"),
                                ("recommande", StaffingPlan.Status.DRAFT, "Planning recommandé (IA + risque)")):
        o = outlook.plans[kind]
        plan = StaffingPlan.objects.create(date=day, kind=kind, status=status, title=title, forecast=forecast,
                                           alpha=None if kind == "actuel" else load_costs().get("risk_alpha"),
                                           **o.summary)
        PlanInterval.objects.bulk_create([
            PlanInterval(plan=plan, ts=ts, agents_required=int(need[ts]), agents_scheduled=int(o.agents[ts]),
                         undercap_probability=float(o.undercap[ts]), expected_loss=float(o.expected_loss[ts]),
                         expected_service_level=float(o.service_level[ts])) for ts in o.agents.index])
        Decision.objects.create(plan=plan, action=Decision.Action.CREATED,
                                comment="Créé automatiquement par le cycle quotidien")
        plans[kind] = plan

    persist_shifts(plans["recommande"], outlook)

    for _, a in outlook.alerts.iterrows():
        Alert.objects.create(date=day, start=a["debut"], end=a["fin"], level=LEVELS[a["niveau"]],
                             source=Alert.Source.RISK, plan=plans["actuel"],
                             undercap_probability=a["proba_sous_capacite_max"], expected_loss=a["perte_attendue"],
                             recommended_reinforcement=a["renfort_recommande"], message=alert_message(a))
    return plans


def shift_details(outlook) -> dict:
    """Synthese des vacations et prix de la contrainte de vacations (vs besoin ideal)."""
    sol, ideal, rec = outlook.shifts, outlook.ideal.summary, outlook.plans["recommande"].summary
    ideal_total = ideal["cost_agents"] + ideal["expected_loss"]
    shifts_total = rec["cost_agents"] + rec["expected_loss"]
    return {
        "vacations": {"types": int(len(sol.shifts)), "agents": int(sol.shifts["agents"].sum()),
                      "heures_payees": sol.paid_hours, "statut_solveur": sol.status,
                      "ecart_optimum_pct": round(100 * sol.gap, 2), "duree_calcul_s": sol.solve_seconds},
        "besoin_ideal": {"heures": ideal["agent_hours"], "cout_agents": round(ideal["cost_agents"], 2),
                         "perte_attendue": round(ideal["expected_loss"], 2), "cout_total": round(ideal_total, 2)},
        "prix_des_vacations": round(shifts_total - ideal_total, 2),
        "prix_des_vacations_pct": round(100 * (shifts_total - ideal_total) / ideal_total, 2),
    }


def persist_shifts(plan: StaffingPlan, outlook) -> None:
    frame = shifts_frame(outlook.shifts, pd.Timestamp(outlook.day))
    Shift.objects.bulk_create([Shift(plan=plan, start=r.debut, end=r.fin, agents=int(r.agents))
                               for r in frame.itertuples()])
    plan.details = shift_details(outlook)
    plan.save(update_fields=["details"])


def plan_next_day(day: date, run: PipelineRun | None = None) -> dict:
    with step(run, "Prévision et planning du lendemain") as s:
        version, bundle = active_bundle()
        history, events, costs = engine_inputs()
        current = simulator.current_plan_for(day)
        outlook = compute_outlook(bundle, history, events, day, current, costs)
        plans = persist_outlook(outlook, run, version)
        from planning.evaluation import remember_model
        remember_model(version.version, day, outlook.model)
        s.update({"jour": f"{day:%d/%m/%Y}", "appels_prevus": round(outlook.forecast["attendu"].sum()),
                  "alertes": len(outlook.alerts), "vacations": int(len(outlook.shifts.shifts)),
                  "solveur": outlook.shifts.status})
    return plans


# --- Le jour qui vient de s'ecouler --------------------------------------------------------------------
def persist_anomalies(day: date, detection: pd.DataFrame) -> int:
    flagged = detection[detection["niveau"] > 0]
    if flagged.empty:
        return 0
    groups = (flagged.index.to_series().diff() != pd.Timedelta(minutes=30)).cumsum()
    plan = StaffingPlan.objects.filter(date=day, status=StaffingPlan.Status.PUBLISHED).first()
    for _, block in flagged.groupby(groups):
        observed, expected = block["observe"].sum(), block["attendu"].sum()
        gap = 100 * (observed / expected - 1)
        Alert.objects.create(
            date=day, start=block.index[0], end=block.index[-1] + pd.Timedelta(minutes=30),
            level=Alert.Level.HIGH if block["niveau"].max() == 2 else Alert.Level.MEDIUM,
            source=Alert.Source.ANOMALY, plan=plan, observed_volume=observed, expected_volume=expected,
            message=(f"Volume anormal de {block.index[0]:%Hh%M} à "
                     f"{block.index[-1] + pd.Timedelta(minutes=30):%Hh%M} : {observed:.0f} appels "
                     f"observés pour {expected:.0f} attendus ({gap:+.0f} %)"))
    return int(groups.nunique())


def check_anomalies(day: date, run: PipelineRun | None = None) -> int:
    with step(run, "Contrôle des anomalies") as s:
        forecast = DailyForecast.objects.filter(date=day).first()
        if forecast is None:
            s["detail"] = "aucune prévision enregistrée pour cette journée"
            return 0
        expected = pd.Series({i.ts: i.expected for i in forecast.intervals.all()})
        observed = read_sql("SELECT ts, offered FROM core.interval_metrics WHERE ts >= :a AND ts < :b",
                            a=pd.Timestamp(day), b=pd.Timestamp(day) + pd.Timedelta(days=1)).set_index("ts")["offered"]
        _, bundle = active_bundle()
        n = persist_anomalies(day, detect_anomalies(bundle, expected, observed))
        s["anomalies"] = n
        return n


def close_past_risk_alerts(day: date) -> int:
    """Une alerte de risque porte sur une journee a venir : une fois la journee ecoulee, elle est close."""
    from django.utils import timezone
    return Alert.objects.filter(date__lte=day, source=Alert.Source.RISK).exclude(
        status=Alert.Status.RESOLVED).update(status=Alert.Status.RESOLVED, handled_at=timezone.now(),
                                             handling_comment="Journée écoulée : alerte close automatiquement")


# --- Le cycle complet ---------------------------------------------------------------------------------
def run_daily_cycle(run: PipelineRun) -> str:
    """Une journee de la vie de la plateforme (mode demonstration : le simulateur livre les exports)."""
    state = PlatformState.get()
    if state.current_date is None:
        raise RuntimeError("Plateforme non initialisee : lancer  python webapp/manage.py init_platform")
    today = state.current_date + timedelta(days=1)          # la journee qui vient de s'ecouler
    tomorrow = today + timedelta(days=1)
    run.target_date = tomorrow
    run.save(update_fields=["target_date"])

    with step(run, "Réception des exports") as s:
        s["fichiers"] = [Path(p).name for p in simulator.release_day(today)]
    with step(run, "Import et nettoyage") as s:
        report = import_day(today)
        record_events(simulator.incidents_of(today))
        s.update({"appels": report["appels"], "doublons": report["acd_duplicates_removed"],
                  "intervalles_reconstitues": report["intervals_imputed"]})
    check_anomalies(today, run)
    closed = close_past_risk_alerts(today)
    if closed:
        run.steps[-1]["alertes_closes"] = closed
    if tomorrow.day == 1:
        with step(run, "Réentraînement mensuel") as s:
            s["version"] = train_model(tomorrow, run).version
    plan_next_day(tomorrow, run)

    state.current_date = today
    state.save(update_fields=["current_date", "updated_at"])
    return f"Journée du {today:%d/%m/%Y} intégrée, lendemain ({tomorrow:%d/%m/%Y}) planifié."


# --- Initialisation et remise a zero ---------------------------------------------------------------------------
def last_data_day() -> date | None:
    value = read_sql("SELECT max(ts) AS m FROM core.interval_metrics")["m"].iloc[0]
    return None if pd.isna(value) else pd.Timestamp(value).date()
