from datetime import datetime

from django.db import connection, transaction
from django.shortcuts import render

from datetime import timedelta

from django.conf import settings

from accounts.models import ROLE_DESCRIPTIONS, Role
from accounts.roles import role_required
from alerts.models import Alert
from planning.models import DailyForecast, ModelVersion, PipelineRun, PlatformState, StaffingPlan
from portal.navigation import ALL, ITEMS


def data_status() -> dict:
    """Etat des donnees du moteur : derniere demi-heure disponible et volume d'historique."""
    try:
        with transaction.atomic(), connection.cursor() as cur:      # savepoint : une erreur ne bloque pas la requete
            cur.execute("SELECT min(ts), max(ts), count(*) FROM core.interval_metrics")
            first, last, n = cur.fetchone()
        return {"available": n > 0, "first": first, "last": last, "intervals": n}
    except Exception:
        return {"available": False}


def greeting(now: datetime | None = None) -> str:
    hour = (now or datetime.now()).hour
    return "Bonjour" if 5 <= hour < 18 else "Bonsoir"


def cycle_overview() -> dict:
    """Etat du cycle quotidien pour la carte de l'accueil."""
    state = PlatformState.get()
    if state.current_date is None:
        return {"ready": False}
    tomorrow = state.current_date + timedelta(days=1)
    plans = {p.kind: p for p in StaffingPlan.objects.filter(date=tomorrow, kind__in=["actuel", "recommande"])}
    current, recommended = plans.get("actuel"), plans.get("recommande")
    alerts = Alert.objects.filter(date=tomorrow, source=Alert.Source.RISK)
    saving = (current.expected_total_cost - recommended.expected_total_cost
              if current and recommended and current.expected_total_cost and recommended.expected_total_cost else 0)
    return {
        "ready": True, "today": state.current_date, "tomorrow": tomorrow,
        "model": ModelVersion.objects.filter(is_active=True).first(),
        "forecast": DailyForecast.objects.filter(date=tomorrow).first(),
        "current": current, "recommended": recommended, "saving": saving,
        "alerts": alerts.count(), "alerts_high": alerts.filter(level=Alert.Level.HIGH).count(),
        "running": PipelineRun.objects.filter(status=PipelineRun.Status.RUNNING).first(),
        "last_run": PipelineRun.objects.first(),
    }


@role_required(*ALL)
def home(request):
    sections = [item for item in ITEMS.values()
                if item.url_name != "home" and request.user.has_role(*item.roles)]
    return render(request, "portal/home.html", {
        "greeting": greeting(), "data": data_status(), "shortcuts": sections,
        "role_description": ROLE_DESCRIPTIONS.get(request.user.role, ""),
        "cycle": cycle_overview(), "demo_mode": settings.DEMO_MODE,
        "can_advance": request.user.has_role(Role.MANAGER),
    })


def page(url_name: str):
    """Page dont la construction est prevue a une etape ulterieure."""
    item = ITEMS[url_name]

    @role_required(*item.roles)
    def view(request):
        return render(request, "portal/coming_soon.html", {"item": item, "page_title": item.label})
    view.__name__ = url_name
    return view


def forbidden(request, exception=None):
    return render(request, "403.html", status=403)
