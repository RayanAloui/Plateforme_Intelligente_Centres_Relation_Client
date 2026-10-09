"""Structure de navigation : une seule source pour le menu, les droits et les pages a venir."""
from dataclasses import dataclass, field

from accounts.models import Role

ALL = (Role.MANAGER, Role.PLANIFICATEUR, Role.ADMINISTRATEUR)
ADMIN = (Role.ADMINISTRATEUR,)


@dataclass(frozen=True)
class NavItem:
    label: str
    url_name: str
    icon: str                      # nom d'icone Lucide
    roles: tuple = ALL
    step: str | None = None        # etape de construction si la page n'est pas encore livree
    summary: str = ""
    features: tuple = field(default_factory=tuple)


SECTIONS = [
    ("Pilotage", [
        NavItem("Accueil", "home", "layout-dashboard"),
        NavItem("Alertes", "alerts", "bell-ring",
                summary="Le centre d'alertes graduées de la plateforme.",
                features=("Alertes faibles, moyennes et élevées", "Accusé de réception",
                          "Renfort recommandé applicable en un clic")),
    ]),
    ("Prévoir", [
        NavItem("Prévision", "forecast", "chart-spline",
                summary="La prévision à J+1 et son incertitude.",
                features=("Fourchettes à 80 % et 98 %", "Anomalies du jour",
                          "Explication de chaque demi-heure (SHAP)")),
        NavItem("Capacité", "capacity", "users-round",
                summary="Effectifs et budget à 1, 2, 3 ou 4 ans.",
                features=("Prévision mensuelle avec fourchettes", "Équivalents temps plein à recruter",
                          "Fiabilité mesurée selon l'horizon")),
    ]),
    ("Décider", [
        NavItem("Planning", "planning", "calendar-clock",
                summary="Du besoin optimal aux vacations réelles des agents.",
                features=("Besoin par demi-heure sous contrainte de risque", "Vacations par MILP (OR-Tools)",
                          "Ajustement, validation, publication", "Export Excel et PDF")),
        NavItem("Risque", "risk", "shield-alert",
                summary="Le risque opérationnel du planning, en euros.",
                features=("Perte attendue, VaR et Expected Shortfall", "Probabilité de sous-capacité",
                          "Distribution des pertes simulées")),
        NavItem("What-if", "whatif", "sliders-horizontal",
                summary="Tester une hypothèse et voir toutes ses conséquences.",
                features=("Volume, absences, budget, risque toléré", "Comparaison avant / après",
                          "Transformer un scénario en planning")),
    ]),
    ("Suivre", [
        NavItem("Historique", "history", "history",
                summary="Ce qui était prévu, ce qui a été décidé, ce qui s'est passé.",
                features=("Prévu vs réalisé", "Décisions et ajustements", "Qualité des recommandations")),
        NavItem("Assistant IA", "assistant", "sparkles",
                summary="Posez vos questions en français sur les chiffres de la plateforme.",
                features=("Modele local Ollama", "Réponses fondées sur les données en base",
                          "Aucun chiffre inventé")),
    ]),
    ("Administration", [
        NavItem("Paramètres", "settings", "settings-2", roles=ADMIN,
                summary="Coûts, seuils d'alerte, risque toléré, règles de vacations.",
                features=("Paramètres économiques", "Seuils d'alerte", "Règles de temps de travail")),
        NavItem("Modèles", "models", "cpu", roles=ADMIN,
                summary="Le suivi des modèles de prévision.",
                features=("Version en service et performances", "Détection de dérive", "Réentraînement")),
        NavItem("Utilisateurs", "users", "users", roles=ADMIN,
                summary="Comptes et rôles.",
                features=("Création de comptes", "Attribution des rôles", "Désactivation")),
    ]),
]

ITEMS = {item.url_name: item for _, items in SECTIONS for item in items}


def menu_for(user) -> list[tuple[str, list[NavItem]]]:
    """Sections et pages visibles pour cet utilisateur."""
    visible = []
    for title, items in SECTIONS:
        allowed = [i for i in items if user.has_role(*i.roles)]
        if allowed:
            visible.append((title, allowed))
    return visible
