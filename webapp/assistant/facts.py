"""La fiche de faits : ce que la plateforme sait, et que l'assistant a le droit de dire.

Chaque fonction lit les donnees deja calculees (previsions, plannings, risque, alertes...) et
renvoie des lignes "libelle : valeur", avec des nombres deja arrondis et formates.
"""
from datetime import date, timedelta

import pandas as pd

from alerts.models import Alert
from planning.models import DailyForecast, ModelVersion, StaffingPlan
from planning.selectors import realized

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
FACTORS = {"heure de la journee": "de l'heure de la journée", "jour de la semaine": "du jour de la semaine",
           "saison": "de la saison", "jour ferie": "du jour férié", "lendemain de ferie": "du lendemain de férié",
           "vacances scolaires": "des vacances scolaires", "campagne commerciale": "d'une campagne commerciale"}


def n(value, decimals=0) -> str:
    """Nombre au format francais : 5 885 ; 12,5."""
    if value is None:
        return "inconnu"
    text = f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",")
    return text


def pct(value, decimals=0) -> str:
    return f"{n(100 * value, decimals)} %" if value is not None else "inconnu"


def day_name(d: date) -> str:
    return f"{JOURS[d.weekday()]} {d:%d/%m/%Y}"


def plan_label(plan: StaffingPlan) -> str:
    kind = plan.get_kind_display()
    kind = kind if kind.startswith("Planning") else f"Planning {kind[0].lower()}{kind[1:]}"
    return f"{kind} n°{plan.pk} ({plan.get_status_display().lower()})"


def in_force(day: date):
    return StaffingPlan.objects.filter(date=day, status=StaffingPlan.Status.PUBLISHED).first()


def decision_plans(day: date) -> list[StaffingPlan]:
    """Planning en vigueur, planning recommande et ajustements : les scenarios what-if restent dans leur page."""
    plans = StaffingPlan.objects.filter(date=day).exclude(status=StaffingPlan.Status.SUPERSEDED)
    return [p for p in plans.order_by("created_at")
            if p.status == StaffingPlan.Status.PUBLISHED or p.kind in ("recommande", "ajuste")]


def hours_difference(a: StaffingPlan, b: StaffingPlan) -> str:
    diff = (a.agent_hours or 0) - (b.agent_hours or 0)
    if abs(diff) < 0.5:
        return "le même nombre d'heures d'agents"
    return f"{n(abs(diff))} heures d'agents de {'plus' if diff > 0 else 'moins'}"


def forecast_facts(day: date, hour: str | None) -> list[str]:
    fc = DailyForecast.objects.filter(date=day).first()
    if fc is None:
        return [f"Aucune prévision n'existe pour le {day_name(day)}."]
    intervals = list(fc.intervals.order_by("ts"))
    peak = max(intervals, key=lambda i: i.expected)
    lines = [f"Journée concernée : {day_name(day)}",
             f"Appels prévus sur la journée : {n(fc.total_expected)} (entre {n(fc.total_q10)} et {n(fc.total_q90)} dans 8 cas sur 10)",
             f"Pic prévu : {n(peak.expected)} appels par demi-heure à {peak.ts:%Hh%M}"]
    if fc.level_total:
        lines.append(f"Niveau du jour prévu par le SARIMAX (tendance, jour de la semaine, calendrier) : {n(fc.level_total)} appels")
    if hour:
        slot = next((i for i in intervals if i.ts.strftime("%H:%M") == hour), None)
        if slot:
            lines.append(f"Prévision à {slot.ts:%Hh%M} : {n(slot.expected)} appels (entre {n(slot.q10)} et {n(slot.q90)} dans 8 cas sur 10)")
            effects = sorted(slot.explanation.items(), key=lambda kv: -abs(kv[1]))[:3]
            for name, effect in effects:
                lines.append(f"Effet {FACTORS.get(name, 'de ' + name)} sur la demi-heure de {slot.ts:%Hh%M} : "
                             f"{'+' if effect >= 0 else ''}{n(effect, 1)} %")
    return lines


def planning_facts(day: date) -> list[str]:
    plans = decision_plans(day)
    if not plans:
        return [f"Aucun planning n'existe pour le {day_name(day)}."]
    lines = []
    for p in plans:
        lines.append(f"{plan_label(p)} : {n(p.agent_hours)} heures d'agents, coût des agents {n(p.cost_agents)} €, "
                     f"perte attendue {n(p.expected_loss)} €, coût total attendu {n(p.expected_total_cost)} €, "
                     f"service level attendu {pct(p.expected_service_level)}")
        vac = (p.details or {}).get("vacations")
        if vac:
            lines.append(f"Vacations du planning n°{p.pk} : {vac['types']} types de vacations, {vac['agents']} agents")
    current = next((p for p in plans if p.kind == "actuel"), None)
    rec = next((p for p in plans if p.kind == "recommande"), None)
    if current and rec and current.expected_total_cost and rec.expected_total_cost:
        saving = current.expected_total_cost - rec.expected_total_cost
        lines.append(f"Le planning recommandé utilise {hours_difference(rec, current)} que le planning actuel, "
                     f"pour un coût total attendu {n(abs(saving))} € {'plus faible' if saving >= 0 else 'plus élevé'}")
    force = in_force(day)
    if force:
        lines.append(f"Planning en vigueur : {plan_label(force)}")
    return lines


def risk_facts(day: date, hour: str | None) -> list[str]:
    plans = decision_plans(day)
    lines = []
    for p in plans:
        worst = p.intervals.order_by("-undercap_probability").first()
        if worst is None:
            continue
        lines.append(f"{plan_label(p)} : probabilité de sous-capacité maximale {pct(worst.undercap_probability)} "
                     f"à {worst.ts:%Hh%M}, VaR 95 % {n(p.var95)} €, perte moyenne des 5 % pires journées {n(p.es95)} €")
    force, rec = in_force(day), next((p for p in plans if p.kind == "recommande"), None)
    if hour and force:
        row = next((r for r in force.intervals.all() if r.ts.strftime("%H:%M") == hour), None)
        if row:
            lines.append(f"À {row.ts:%Hh%M} avec le planning en vigueur : {row.agents_scheduled} agents planifiés pour un besoin "
                         f"de {row.agents_required}, probabilité de sous-capacité {pct(row.undercap_probability)}, "
                         f"perte attendue {n(row.expected_loss)} € sur la demi-heure")
            if row.agents_required > row.agents_scheduled:
                lines.append(f"Renfort nécessaire à {row.ts:%Hh%M} : {row.agents_required - row.agents_scheduled} agents")
    if force and rec and force.pk != rec.pk:
        gaps = [(r.ts, r.agents_required - r.agents_scheduled) for r in force.intervals.order_by("ts")]
        short = [(ts, g) for ts, g in gaps if g > 0]
        if short:
            ts, g = max(short, key=lambda x: x[1])
            lines.append(f"Avec le planning en vigueur, il manque des agents sur {len(short)} demi-heures ; "
                         f"le plus grand manque est de {g} agents à {ts:%Hh%M}")
    return lines or [f"Aucune donnée de risque pour le {day_name(day)}."]


def alert_facts(day: date) -> list[str]:
    alerts = Alert.objects.filter(date=day).exclude(status=Alert.Status.RESOLVED).order_by("-level", "start")
    if not alerts:
        return [f"Aucune alerte ouverte pour le {day_name(day)}."]
    lines = [f"Alertes ouvertes pour le {day_name(day)} : {alerts.count()}"]
    for a in alerts[:6]:
        if a.source == Alert.Source.RISK:
            lines.append(f"Alerte {a.get_level_display().lower()} de {a.start:%Hh%M} à {a.end:%Hh%M} : sous-capacité "
                         f"{pct(a.undercap_probability)}, perte attendue {n(a.expected_loss)} €, renfort recommandé "
                         f"{a.recommended_reinforcement} agents")
        else:
            lines.append(f"Anomalie {a.get_level_display().lower()} : {a.message}")
    return lines


def history_facts(day: date) -> list[str]:
    real = realized(day)
    fc = DailyForecast.objects.filter(date=day).first()
    if real is None or fc is None:
        return [f"La journée du {day_name(day)} n'est pas encore réalisée."]
    actual = real["offered"].sum()
    sl = (real["service_level"] * real["offered"]).sum() / max(actual, 1)
    lines = [f"Journée réalisée : {day_name(day)}",
             f"Appels prévus la veille : {n(fc.total_expected)} ; appels réellement reçus : {n(actual)} "
             f"(la prévision a {'surestimé' if fc.total_expected > actual else 'sous-estimé'} la demande de "
             f"{n(abs(100 * (fc.total_expected - actual) / actual), 1)} %)",
             f"Service level réalisé : {pct(sl)} ; appels abandonnés : {n(real['abandoned'].sum())}"]
    anomalies = Alert.objects.filter(date=day, source=Alert.Source.ANOMALY).count()
    lines.append(f"Anomalies détectées ce jour-là : {anomalies}")
    return lines


def capacity_facts(year: int | None) -> list[str]:
    from planning.insights import capacity_data
    plan = capacity_data(48)["plan"]
    months = plan[plan.index.year == year] if year else plan.iloc[:12]
    if months.empty:
        return [f"La prévision de capacité couvre jusqu'à {plan.index[-1]:%m/%Y} seulement."]
    label = f"en {year}" if year else "sur les 12 prochains mois"
    return [f"Effectif nécessaire {label} : {n(months['etp_p50'].mean())} ETP en moyenne "
            f"({n(months['etp_p90'].mean())} ETP dans le scénario haut)",
            f"Mois le plus chargé {label} : {months['etp_p50'].idxmax():%m/%Y} avec {n(months['etp_p50'].max())} ETP",
            f"Budget agents {label} : {n(months['budget_p50'].sum())} € (jusqu'à {n(months['budget_p90'].sum())} €)",
            f"Appels prévus {label} : {n(months['p50'].sum())}",
            *(["Au-delà de 24 mois, la fourchette ne couvre pas les ruptures (nouveau client, nouvelle offre)."]
              if year and year >= date.today().year + 2 else [])]


def model_facts() -> list[str]:
    from planning.monitoring import drift_status, live_performance
    active = ModelVersion.objects.filter(is_active=True).first()
    if active is None:
        return ["Aucun modèle de prévision n'est actif."]
    m = active.metrics or {}
    drift = drift_status(live_performance(), m)
    lines = [f"Modèle en service : {active.version}, hybride SARIMAX + LightGBM, réentraîné chaque mois",
             f"Erreur mesurée hors échantillon (WAPE) : {n(m.get('WAPE_%'), 1)} % ; biais {n(m.get('biais_%'), 1)} % ; "
             f"la fourchette à 80 % contient la réalité dans {n(m.get('couverture_fourchette_80_%'), 0)} % des cas",
             f"Diagnostic en exploitation : {drift['title']}"]
    if drift.get("wape") is not None:
        lines.append(f"Erreur moyenne des 7 dernières journées : {n(drift['wape'], 1)} %")
    return lines


def parameter_facts() -> list[str]:
    from crc.risk.costs import load_costs
    c = load_costs()
    return [f"Coût d'une heure d'agent : {n(c['cost_agent_hour'])} €", f"Coût d'un appel abandonné : {n(c['cost_abandoned_call'])} €",
            f"Service level cible : {pct(c['sla_target_ratio'])} des appels en moins de {n(c['sla_target_seconds'])} secondes",
            f"Risque de sous-capacité toléré : {pct(c.get('risk_alpha', 0.05))}",
            f"Seuils d'alerte : moyenne à {pct(c.get('alert_medium_threshold', 0.1))}, élevée à {pct(c.get('alert_high_threshold', 0.2))}"]


def level_of(p: float) -> str:
    from crc.risk.costs import load_costs
    c = load_costs()
    if p >= c.get("alert_high_threshold", 0.2):
        return "élevé"
    return "moyen" if p >= c.get("alert_medium_threshold", 0.1) else "faible"


def key_points(question) -> list[str]:
    """Conclusions calculees par la plateforme. Elles forment le debut de la reponse, telles quelles :
    l'assistant ne les deduit pas, il peut seulement les expliquer."""
    import re
    from assistant.understanding import TOPICS, normalize
    day, t, points = question.day, normalize(question.text), []
    asked = {name for name, words in TOPICS.items() if any(w in t for w in words)}
    force = in_force(day) if day else None
    fc = DailyForecast.objects.filter(date=day).first() if day else None

    if day and "risque" in question.topics and force:
        rows = list(force.intervals.order_by("ts"))
        worst = max(rows, key=lambda r: r.undercap_probability or 0) if rows else None
        row = next((r for r in rows if r.ts.strftime("%H:%M") == question.hour), None) if question.hour else None
        if row:
            level = level_of(row.undercap_probability or 0)
            if "eleve" in t and level == "faible":
                points.append(f"Contrairement à ce que suppose la question, le risque n'est pas élevé à {row.ts:%Hh%M}")
            points.append(f"À {row.ts:%Hh%M}, le risque de sous-capacité est {level} : "
                          f"{pct(row.undercap_probability)} avec le planning en vigueur, qui prévoit "
                          f"{row.agents_scheduled} agents pour un besoin de {row.agents_required}")
            gap = row.agents_required - row.agents_scheduled
            if gap > 0:
                agents = f"{gap} agent{'s' if gap > 1 else ''}"
                points.append(f"Le planning en vigueur prévoit {agents} de moins que l'effectif recommandé "
                              f"à {row.ts:%Hh%M} (qui inclut une marge de prudence) : le risque reste {level}, "
                              f"mais un renfort de {agents} le réduirait")
        if worst and (row is None or worst.pk != row.pk) and ("risque" in asked or row is not None):
            points.append(f"Le moment le plus risqué de la journée est {worst.ts:%Hh%M} "
                          f"({pct(worst.undercap_probability)}, risque {level_of(worst.undercap_probability or 0)})")

    if day and "planning" in question.topics and force and re.search(r"en plus|renfort|manque|suffi|combien d.agent", t):
        short = [r for r in force.intervals.order_by("ts") if r.agents_required > r.agents_scheduled]
        if not short:
            points.append("Aucun renfort n'est nécessaire demain : le planning en vigueur couvre le besoin "
                          "sur toutes les demi-heures de la journée")
        else:
            top = max(short, key=lambda r: r.agents_required - r.agents_scheduled)
            points.append(f"Il faut jusqu'à {top.agents_required - top.agents_scheduled} agents de plus (à {top.ts:%Hh%M}) : "
                          f"le planning en vigueur manque d'agents sur {len(short)} demi-heures, "
                          f"de {short[0].ts:%Hh%M} à {short[-1].ts:%Hh%M}")
    elif day and "planning" in question.topics and "planning" in asked and force:
        rec = next((p for p in decision_plans(day) if p.kind == "recommande"), None)
        if rec and rec.pk != force.pk and rec.expected_total_cost and force.expected_total_cost:
            saving = force.expected_total_cost - rec.expected_total_cost
            points.append(f"Le planning recommandé coûterait {n(abs(saving))} € de {'moins' if saving >= 0 else 'plus'} "
                          f"que le planning en vigueur, avec {hours_difference(rec, force)}")

    if "capacite" in question.topics:
        from planning.insights import capacity_data
        plan = capacity_data(48)["plan"]
        months = plan[plan.index.year == question.year] if question.year else plan.iloc[:12]
        if not months.empty:
            label = f"en {question.year}" if question.year else "sur les 12 prochains mois"
            points.append(f"Il faut prévoir {n(months['etp_p50'].mean())} ETP en moyenne {label}, "
                          f"et {n(months['etp_p90'].mean())} ETP pour être couvert dans 9 cas sur 10")

    if fc and "prevision" in question.topics:
        slot = fc.intervals.filter(ts__hour=int(question.hour[:2]), ts__minute=int(question.hour[3:])).first() \
            if question.hour else None
        if slot and slot.explanation:
            name, effect = max(slot.explanation.items(), key=lambda kv: abs(kv[1]))
            points.append(f"À {slot.ts:%Hh%M}, {n(slot.expected)} appels sont prévus ; le facteur principal est l'effet "
                          f"{FACTORS.get(name, 'de ' + name)} ({'+' if effect >= 0 else ''}{n(effect, 1)} %)")
        elif "prevision" in asked:
            peak = max(fc.intervals.all(), key=lambda i: i.expected)
            points.append(f"{n(fc.total_expected)} appels sont prévus le {day_name(day)} (entre {n(fc.total_q10)} et "
                          f"{n(fc.total_q90)} dans 8 cas sur 10), avec un pic à {peak.ts:%Hh%M}")

    if day and "alertes" in question.topics and "alertes" in asked:
        open_ = Alert.objects.filter(date=day).exclude(status=Alert.Status.RESOLVED)
        high = open_.filter(level=Alert.Level.HIGH).count()
        points.append(f"{open_.count()} alerte{'s' if open_.count() > 1 else ''} ouverte{'s' if open_.count() > 1 else ''} "
                      f"le {day_name(day)}, dont {high} élevée{'s' if high > 1 else ''}" if open_.exists()
                      else f"Aucune alerte ouverte le {day_name(day)}")

    if day and "historique" in question.topics:
        real = realized(day)
        if real is not None and fc:
            actual = real["offered"].sum()
            sl = (real["service_level"] * real["offered"]).sum() / max(actual, 1)
            points.append(f"Le {day_name(day)}, {n(actual)} appels ont été reçus pour {n(fc.total_expected)} prévus, "
                          f"avec un service level de {pct(sl)}")

    if "modele" in question.topics:
        from planning.monitoring import drift_status, live_performance
        active = ModelVersion.objects.filter(is_active=True).first()
        if active:
            drift = drift_status(live_performance(), active.metrics or {})
            detail = (f" : erreur de {n(drift['wape'], 1)} % sur les 7 dernières journées, pour {n(drift['reference'], 1)} % "
                      f"mesurés avant la mise en service") if drift.get("wape") is not None else ""
            state = {"ok": "en bonne santé", "surveiller": "à surveiller",
                     "derive": "en dérive : un réentraînement est conseillé"}.get(drift["level"], "encore en observation")
            points.append(f"Le modèle de prévision est {state}{detail.replace(' : ', ' (', 1) + ')' if detail else ''}")
    return points


def build_sheet(question) -> dict:
    """Fiche complete : conclusions d'abord, puis le detail par theme, dans l'ordre de la question."""
    sections = {}
    points = key_points(question)
    if points:
        sections["À retenir"] = points
    for topic in question.topics:
        if topic == "prevision" and question.day:
            sections["Prévision"] = forecast_facts(question.day, question.hour)
        elif topic == "planning" and question.day:
            sections["Plannings"] = planning_facts(question.day)
        elif topic == "risque" and question.day:
            sections["Risque"] = risk_facts(question.day, question.hour)
        elif topic == "alertes" and question.day:
            sections["Alertes"] = alert_facts(question.day)
        elif topic == "historique" and question.day:
            sections["Journée réalisée"] = history_facts(question.day)
        elif topic == "capacite":
            sections["Capacité"] = capacity_facts(question.year)
        elif topic == "modele":
            sections["Modèle de prévision"] = model_facts()
        elif topic == "parametres":
            sections["Paramètres"] = parameter_facts()
    return sections


def render_sheet(sections: dict) -> str:
    return "\n".join(f"[{title}]\n" + "\n".join(f"- {line}" for line in lines) for title, lines in sections.items())
