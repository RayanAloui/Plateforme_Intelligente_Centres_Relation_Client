from datetime import datetime

from django.db import connection, transaction
from django.shortcuts import render

from accounts.models import ROLE_DESCRIPTIONS
from accounts.roles import role_required
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


@role_required(*ALL)
def home(request):
    sections = [item for item in ITEMS.values()
                if item.url_name != "home" and request.user.has_role(*item.roles)]
    return render(request, "portal/home.html", {
        "greeting": greeting(), "data": data_status(), "shortcuts": sections,
        "role_description": ROLE_DESCRIPTIONS.get(request.user.role, ""),
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
