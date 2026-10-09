"""Centre d'alertes (module 18)."""
from django.db.models import Avg, F, Q
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from accounts.models import Role
from accounts.roles import role_required
from alerts.models import Alert
from planning.models import StaffingPlan
from planning.selectors import platform_today
from portal.navigation import ALL

HANDLERS = (Role.MANAGER, Role.PLANIFICATEUR)
FILTERS = {"ouvertes": ("Ouvertes", ~Q(status=Alert.Status.RESOLVED)),
           "nouvelles": ("Nouvelles", Q(status=Alert.Status.NEW)),
           "resolues": ("Résolues", Q(status=Alert.Status.RESOLVED)),
           "toutes": ("Toutes", Q())}


def human_delay(delta) -> str:
    if delta is None:
        return "—"
    minutes = int(delta.total_seconds() // 60)
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60:02d}"


def decorate(alerts):
    """Ajoute a chaque alerte le lien utile (planning recommande ou prevision du jour)."""
    plans = {p.date: p.pk for p in StaffingPlan.objects.filter(
        date__in={a.date for a in alerts}, kind__in=["recommande", "ajuste", "scenario"]).exclude(
        status=StaffingPlan.Status.SUPERSEDED).order_by("created_at")}
    for a in alerts:
        a.recommended_plan = plans.get(a.date)
    return alerts


@role_required(*ALL)
def alert_list(request):
    key = request.GET.get("filtre", "ouvertes")
    label, condition = FILTERS.get(key, FILTERS["ouvertes"])
    qs = Alert.objects.filter(condition)
    if request.GET.get("niveau") in ("1", "2"):
        qs = qs.filter(level=int(request.GET["niveau"]))
    if request.GET.get("source") in ("risque", "anomalie"):
        qs = qs.filter(source=request.GET["source"])
    alerts = decorate(list(qs.select_related("handled_by").order_by("-date", "-level", "start")[:200]))
    today = platform_today()
    handled = Alert.objects.filter(handled_at__isnull=False, handled_by__isnull=False)
    stats = {
        "open": Alert.objects.exclude(status=Alert.Status.RESOLVED).count(),
        "open_high": Alert.objects.exclude(status=Alert.Status.RESOLVED).filter(level=Alert.Level.HIGH).count(),
        "handled": handled.count(),
        "delay": human_delay(handled.aggregate(d=Avg(F("handled_at") - F("created_at")))["d"]),
    }
    days = {}
    for a in alerts:
        days.setdefault(a.date, []).append(a)
    return render(request, "alerts/list.html", {
        "page_title": "Alertes", "groups": days.items(), "filters": FILTERS, "active": key, "stats": stats,
        "today": today, "can_handle": request.user.has_role(*HANDLERS),
        "level": request.GET.get("niveau", ""), "source": request.GET.get("source", "")})


@require_POST
@role_required(*HANDLERS)
def alert_handle(request, pk, action):
    alert = get_object_or_404(Alert, pk=pk)
    comment = request.POST.get("comment", "").strip()
    (alert.acknowledge if action == "prendre" else alert.resolve)(request.user, comment)
    alert = decorate([alert])[0]
    return render(request, "alerts/_card.html", {"a": alert, "can_handle": True})
