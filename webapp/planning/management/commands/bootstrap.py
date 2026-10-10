"""Mise en service complete d'une plateforme neuve, en une commande (idempotente).

    python webapp/manage.py bootstrap
    docker compose run --rm web python webapp/manage.py bootstrap

1. historique (Phase 1) s'il est absent : calendrier, generation, nettoyage, analyse exploratoire
2. tables de l'application (migrations)
3. comptes de demonstration s'il n'existe aucun utilisateur
4. plateforme : monde simule, modele de prevision, planification du lendemain
"""
import subprocess
import sys

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection

from accounts.models import User
from planning.models import PlatformState


def history_rows() -> int:
    with connection.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.interval_metrics")
        return cur.fetchone()[0]


class Command(BaseCommand):
    help = "Met en service la plateforme de bout en bout (sans rien refaire de ce qui existe deja)."

    def step(self, title):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {title}"))

    def handle(self, *args, **options):
        self.step("1/4 Historique")
        rows = history_rows()
        if rows:
            self.stdout.write(f"Déjà présent : {rows} demi-heures.")
        else:
            self.stdout.write("Reconstruction de la Phase 1 (environ une minute)...")
            subprocess.run([sys.executable, "-m", "crc.rebuild"], check=True)

        self.step("2/4 Tables de l'application")
        call_command("migrate", interactive=False, verbosity=0)
        self.stdout.write("À jour.")

        self.step("3/4 Comptes")
        if User.objects.exists():
            self.stdout.write(f"Déjà présents : {User.objects.count()} comptes.")
        else:
            call_command("create_demo_users")

        self.step("4/4 Plateforme")
        if PlatformState.get().current_date:
            self.stdout.write(f"Déjà initialisée (date de la plateforme : {PlatformState.get().current_date:%d/%m/%Y}).")
        else:
            call_command("init_platform")
        self.stdout.write(self.style.SUCCESS("\nPlateforme prête."))
        self.stdout.write("Pour l'ouvrir : python webapp/manage.py runserver, puis http://127.0.0.1:8000\n"
                          "(avec Docker, le service web la sert déjà sur http://localhost:8000)")
