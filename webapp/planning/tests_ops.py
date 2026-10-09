"""Tests des commandes d'exploitation (planificateur, mise en service)."""
from datetime import datetime
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from planning.management.commands.run_scheduler import next_run
from planning.models import PlatformState


class SchedulerTests(SimpleTestCase):
    def test_next_run_is_today_or_tomorrow(self):
        self.assertEqual(next_run(datetime(2025, 1, 6, 5, 0), "06:00"), datetime(2025, 1, 6, 6, 0))
        self.assertEqual(next_run(datetime(2025, 1, 6, 6, 0), "06:00"), datetime(2025, 1, 7, 6, 0))
        self.assertEqual(next_run(datetime(2025, 1, 6, 23, 59), "06:30"), datetime(2025, 1, 7, 6, 30))


class BootstrapTests(TestCase):
    def test_bootstrap_is_idempotent_and_skips_what_exists(self):
        state = PlatformState.get()
        state.current_date = datetime(2025, 1, 6).date()
        state.save()
        out = StringIO()
        with mock.patch("planning.management.commands.bootstrap.subprocess.run") as rebuild, \
                mock.patch("planning.management.commands.bootstrap.history_rows", return_value=52608):
            call_command("bootstrap", stdout=out)
        rebuild.assert_not_called()                                   # historique deja present
        text = out.getvalue()
        self.assertIn("Déjà présent : 52608 demi-heures", text)
        self.assertIn("Déjà initialisée", text)
        self.assertIn("Plateforme prête", text)
