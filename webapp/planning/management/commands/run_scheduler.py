"""Planificateur : lance le cycle quotidien chaque jour a l'heure CYCLE_TIME (par defaut 06:00).

    python webapp/manage.py run_scheduler          # service "scheduler" de docker-compose (profil production)
"""
import os
import time
from datetime import datetime, timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import close_old_connections


def next_run(now: datetime, hhmm: str) -> datetime:
    hour, minute = (int(x) for x in hhmm.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return target if target > now else target + timedelta(days=1)


class Command(BaseCommand):
    help = "Execute le cycle quotidien tous les jours a heure fixe."

    def handle(self, *args, **options):
        hhmm = os.environ.get("CYCLE_TIME", "06:00")
        self.stdout.write(f"Planificateur démarré : cycle quotidien chaque jour à {hhmm}.")
        while True:
            target = next_run(datetime.now(), hhmm)
            self.stdout.write(f"Prochain cycle : {target:%d/%m/%Y %H:%M}")
            time.sleep(max(1, (target - datetime.now()).total_seconds()))
            close_old_connections()
            try:
                call_command("run_daily_cycle")
            except Exception as exc:                       # le planificateur ne doit jamais s'arreter
                self.stderr.write(f"Échec du cycle : {exc}")
