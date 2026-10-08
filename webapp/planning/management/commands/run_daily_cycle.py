"""Execute le cycle quotidien (pour le planificateur de taches ou la ligne de commande).

    python webapp/manage.py run_daily_cycle             # un jour
    python webapp/manage.py run_daily_cycle --days 7    # une semaine d'exploitation
"""
from django.core.management.base import BaseCommand

from planning import services
from planning.models import PipelineRun
from planning.tasks import launch


class Command(BaseCommand):
    help = "Integre la journee ecoulee et planifie le lendemain."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=1)

    def handle(self, *args, **options):
        for _ in range(options["days"]):
            run = launch(PipelineRun.Kind.DAILY, None, services.run_daily_cycle, background=False)
            if run is None:
                self.stderr.write("Un traitement est deja en cours.")
                return
            if run.status != PipelineRun.Status.SUCCESS:
                self.stderr.write(f"Echec : {run.message}")
                return
            durations = ", ".join(f"{s['etape']} {s['duree_s']} s" for s in run.steps)
            self.stdout.write(self.style.SUCCESS(run.message) + f"  ({durations})")
