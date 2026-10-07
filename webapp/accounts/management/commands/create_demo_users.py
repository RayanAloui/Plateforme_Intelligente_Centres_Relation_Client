"""Cree (ou met a jour) un compte de demonstration par role.

    python webapp/manage.py create_demo_users
"""
import os

from django.core.management.base import BaseCommand

from accounts.models import Role, User

DEMO_USERS = [
    ("manager", "Sarah", "Benali", Role.MANAGER),
    ("planificateur", "Karim", "Haddad", Role.PLANIFICATEUR),
    ("admin", "Ines", "Mansour", Role.ADMINISTRATEUR),
]


class Command(BaseCommand):
    help = "Cree les comptes de demonstration (un par role)."

    def handle(self, *args, **options):
        password = os.environ.get("DEMO_PASSWORD", "Demo2024!")
        for username, first, last, role in DEMO_USERS:
            user, created = User.objects.get_or_create(username=username)
            user.first_name, user.last_name, user.role = first, last, role
            user.is_staff = user.is_superuser = role == Role.ADMINISTRATEUR
            user.set_password(password)
            user.save()
            self.stdout.write(f"{'cree' if created else 'mis a jour':>10} : {username:<14} ({role.label})")
        self.stdout.write(self.style.SUCCESS(f"Mot de passe commun : {password}"))
