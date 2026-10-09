"""Comprendre la question : de quoi parle-t-elle, quelle journee, quelle heure, quelle annee ?

Analyse volontairement simple et previsible (mots-cles), plutot que confiee au modele de
langue : c'est la plateforme, et non le modele, qui decide quelles donnees sont pertinentes.
"""
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta

TOPICS = {
    "prevision": ("prevision", "prevu", "appel", "volume", "pic", "charge", "demande", "pourquoi"),
    "risque": ("risque", "sous-capacite", "sous capacite", "var", "perte", "danger", "probabilite", "pire"),
    "planning": ("planning", "agent", "renfort", "vacation", "effectif", "equipe", "shift", "combien de personnes"),
    "alertes": ("alerte", "urgent", "probleme", "attention"),
    "historique": ("hier", "realise", "s'est passe", "bilan", "erreur", "ecart", "semaine derniere"),
    "capacite": ("recrut", "etp", "temps plein", "budget", "long terme", "annee", "capacite", "embauch"),
    "modele": ("modele", "fiable", "fiabilite", "precision", "derive", "reentrain", "confiance"),
    "parametres": ("parametre", "cout", "seuil", "cible", "tarif"),
}
DEFAULT_TOPICS = ["prevision", "planning", "alertes"]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


@dataclass
class Question:
    text: str
    topics: list[str] = field(default_factory=list)
    day: date | None = None
    day_label: str = "demain"
    hour: str | None = None              # "HH:MM"
    year: int | None = None


def understand(text: str, today: date | None, previous_topics: list[str] | None = None) -> Question:
    t = normalize(text)
    topics = [name for name, words in TOPICS.items() if any(w in t for w in words)]
    matched = bool(topics)
    if not topics:
        topics = list(previous_topics or DEFAULT_TOPICS)
    if "risque" in topics and "prevision" not in topics and re.search(r"pourquoi|explique", t):
        topics.append("prevision")
    if "planning" in topics and "risque" not in topics and re.search(r"en plus|renfort|manque|suffis", t):
        topics.append("risque")

    q = Question(text=text, topics=topics)
    tomorrow = today + timedelta(days=1) if today else None
    explicit = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
    if explicit and today:
        d, m, y = int(explicit.group(1)), int(explicit.group(2)), explicit.group(3)
        year = int(y) + (2000 if y and len(y) == 2 else 0) if y else today.year
        try:
            q.day, q.day_label = date(year, m, d), f"le {d:02d}/{m:02d}/{year}"
        except ValueError:
            pass
    elif "avant-hier" in t and today:
        q.day, q.day_label = today - timedelta(days=2), "avant-hier"
    elif "hier" in t and today:
        q.day, q.day_label = today - timedelta(days=1), "hier"
    elif "aujourd" in t and today:
        q.day, q.day_label = today, "aujourd'hui"
    else:
        q.day = today if topics == ["historique"] else tomorrow
        q.day_label = "la dernière journée réalisée" if topics == ["historique"] else "demain"
    if q.day_label in ("hier", "aujourd'hui", "avant-hier"):
        if not matched:
            q.topics = ["historique"]
        elif "historique" not in q.topics:
            q.topics.append("historique")

    hour = re.search(r"\b(\d{1,2})\s*h\s*(\d{2})?\b|\b(\d{1,2}):(\d{2})\b", t)
    if hour:
        h = int(hour.group(1) or hour.group(3))
        mnt = int(hour.group(2) or hour.group(4) or 0)
        if 0 <= h < 24:
            q.hour = f"{h:02d}:{30 if mnt >= 30 else 0:02d}"
    year = re.search(r"\b(20[2-3]\d)\b", t)
    if year:
        q.year = int(year.group(1))
        if "capacite" not in q.topics and q.year > (today.year if today else 0):
            q.topics.append("capacite")
    if "capacite" in q.topics and "demain" not in t and not explicit:
        q.topics = ["capacite"]                     # question de long terme : rien sur la journee de demain
    return q
