from django.db import connection, transaction

from portal.navigation import menu_for


def last_data_timestamp():
    """Derniere demi-heure disponible dans core (affichee dans la barre superieure)."""
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SELECT max(ts) FROM core.interval_metrics")
            return cur.fetchone()[0]
    except Exception:
        return None


def navigation(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    match = getattr(request, "resolver_match", None)
    return {"menu": menu_for(request.user), "active_page": match.url_name if match else None,
            "data_last": last_data_timestamp(), "open_alerts": open_alert_count()}


def open_alert_count() -> int:
    """Alertes non resolues pour la journee en cours et le lendemain (pastille du menu)."""
    from alerts.models import Alert
    from planning.models import PlatformState
    try:
        today = PlatformState.get().current_date
        if today is None:
            return 0
        return Alert.objects.filter(date__gte=today).exclude(status=Alert.Status.RESOLVED).count()
    except Exception:
        return 0
