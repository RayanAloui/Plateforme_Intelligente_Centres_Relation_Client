"""Les alertes suivent les decisions : quand un nouveau planning est publie, les alertes de
risque de la journee sont recalculees sur ce planning."""
import pandas as pd
from django.db import transaction
from django.utils import timezone

from alerts.models import Alert
from crc.app.alerts import build_alerts, interval_levels, message
from crc.risk.costs import load_costs

LEVELS = {"Moyen": Alert.Level.MEDIUM, "Eleve": Alert.Level.HIGH}


@transaction.atomic
def realign_alerts(plan, user) -> int:
    """Clot les alertes de risque ouvertes du jour et cree celles du planning desormais en vigueur."""
    now = timezone.now()
    Alert.objects.filter(date=plan.date, source=Alert.Source.RISK).exclude(status=Alert.Status.RESOLVED).update(
        status=Alert.Status.RESOLVED, handled_by=user, handled_at=now,
        handling_comment=f"Planning n°{plan.pk} publié : risque recalculé sur ce planning")
    rows = list(plan.intervals.order_by("ts").values("ts", "undercap_probability", "expected_loss",
                                                      "agents_scheduled", "agents_required"))
    if not rows:
        return 0
    df = pd.DataFrame(rows).set_index("ts")
    costs = load_costs()
    level = interval_levels(df["undercap_probability"].fillna(0), high=costs.get("alert_high_threshold", 0.2),
                            medium=costs.get("alert_medium_threshold", 0.1))
    alerts = build_alerts(level, df["undercap_probability"].fillna(0), df["expected_loss"].fillna(0),
                          df["agents_scheduled"], df["agents_required"])
    for _, a in alerts.iterrows():
        Alert.objects.create(date=plan.date, start=a["debut"], end=a["fin"], level=LEVELS[a["niveau"]],
                             source=Alert.Source.RISK, plan=plan,
                             undercap_probability=a["proba_sous_capacite_max"], expected_loss=a["perte_attendue"],
                             recommended_reinforcement=a["renfort_recommande"], message=message(a))
    return len(alerts)


def open_alerts(since):
    return Alert.objects.filter(date__gte=since).exclude(status=Alert.Status.RESOLVED)
