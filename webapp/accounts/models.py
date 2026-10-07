"""Utilisateurs et roles de la plateforme."""
from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    MANAGER = "manager", "Manager"
    PLANIFICATEUR = "planificateur", "Planificateur"
    ADMINISTRATEUR = "administrateur", "Administrateur"


ROLE_DESCRIPTIONS = {
    Role.MANAGER: "Consulte, simule, valide les plannings et traite les alertes.",
    Role.PLANIFICATEUR: "Prépare et ajuste les plannings, puis les soumet à validation.",
    Role.ADMINISTRATEUR: "Tous les droits, plus les paramètres, les modèles et les utilisateurs.",
}


class User(AbstractUser):
    role = models.CharField("rôle", max_length=20, choices=Role.choices, default=Role.MANAGER)

    class Meta:
        verbose_name = "utilisateur"

    def has_role(self, *roles: str) -> bool:
        """Un administrateur a tous les droits."""
        return self.is_superuser or self.role == Role.ADMINISTRATEUR or self.role in roles

    @property
    def is_administrator(self) -> bool:
        return self.has_role(Role.ADMINISTRATEUR)

    @property
    def display_name(self) -> str:
        return self.get_full_name() or self.username

    @property
    def initials(self) -> str:
        parts = self.display_name.split()
        return "".join(p[0] for p in parts[:2]).upper() or "?"
