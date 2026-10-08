"""Initialise la plateforme pour l'exploitation (et la demonstration).

    python webapp/manage.py init_platform           # premiere mise en service
    python webapp/manage.py init_platform --reset   # revenir au 31/12/2024 et tout rejouer

1. Le simulateur prepare le monde 2025-2026 (exports livres jour apres jour ensuite).
2. Les campagnes commerciales planifiees sont enregistrees (le marketing les annonce a l'avance).
3. Le modele de prevision est entraine sur tout l'historique et active.
4. La plateforme prepare le lendemain : prevision, plannings, risque, alertes.
"""
import shutil
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from alerts.models import Alert
from crc.ops import simulator
from crc.ops.ingest import record_events
from planning import services
from planning.models import DailyForecast, ModelVersion, PipelineRun, PlatformState, StaffingPlan
from planning.tasks import launch


class Command(BaseCommand):
    help = "Initialise la plateforme : monde simule, modele, et planification du lendemain."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Efface l'exploitation simulee (2025+) et repart du dernier jour d'historique")

    def handle(self, *args, **options):
        if options["reset"]:
            self.reset()

        if not simulator.is_prepared():
            self.stdout.write("Simulateur : generation du monde 2025-2026...")
            simulator.prepare_future(settings.RANDOM_SEED)
        added = record_events(simulator.planned_campaigns())
        self.stdout.write(f"Campagnes commerciales planifiees enregistrees : {added}")

        state = PlatformState.get()
        if state.current_date is None:
            state.current_date = services.last_data_day()
            state.save()
        tomorrow = state.current_date + timedelta(days=1)
        self.stdout.write(f"Date de la plateforme : {state.current_date:%d/%m/%Y} (lendemain : {tomorrow:%d/%m/%Y})")

        if not ModelVersion.objects.filter(is_active=True).exists():
            self.stdout.write("Entrainement du modele de prevision (environ une minute)...")
            version = services.train_model(tomorrow)
            self.stdout.write(f"Modele actif : {version.version}")

        self.stdout.write("Prevision, plannings et risque du lendemain...")
        run = launch(PipelineRun.Kind.REPLAN, None,
                     lambda r: services.plan_next_day(tomorrow, r) and "Lendemain planifie", background=False)
        if run is None or run.status != PipelineRun.Status.SUCCESS:
            self.stderr.write(f"Echec : {run.message if run else 'un traitement est deja en cours'}")
            return
        self.stdout.write(self.style.SUCCESS("Plateforme prete. Lancez :  python webapp/manage.py runserver"))

    def reset(self):
        first_future = simulator.FUTURE_START
        self.stdout.write(f"Remise a zero de l'exploitation a partir du {first_future:%d/%m/%Y}...")
        with connection.cursor() as cur:
            cur.execute("DELETE FROM core.interval_metrics WHERE ts >= %s", [first_future])
            cur.execute("DELETE FROM ref.events WHERE start_ts >= %s", [first_future])
            for table in ("acd_export", "wfm_roster"):
                cur.execute(f"DELETE FROM raw.{table} WHERE source_file ~ '^(acd|wfm)_[0-9]{{8}}[.]csv$'")
        Alert.objects.all().delete()
        StaffingPlan.objects.all().delete()
        DailyForecast.objects.all().delete()
        PipelineRun.objects.all().delete()
        ModelVersion.objects.filter(cutoff__gt=first_future).delete()
        state = PlatformState.get()
        state.current_date = None
        state.save()
        shutil.rmtree(simulator.INBOX_DIR, ignore_errors=True)
