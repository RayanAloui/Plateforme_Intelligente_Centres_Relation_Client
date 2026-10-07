from datetime import date, datetime
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from accounts.models import User
from alerts.models import Alert


class AlertTests(TestCase):
    def test_acknowledgement_is_traced(self):
        call_command("create_demo_users", stdout=StringIO())
        manager = User.objects.get(username="manager")
        alert = Alert.objects.create(date=date(2025, 1, 6), start=datetime(2025, 1, 6, 14),
                                     end=datetime(2025, 1, 6, 16), level=Alert.Level.HIGH,
                                     source=Alert.Source.RISK, undercap_probability=0.24,
                                     expected_loss=620, recommended_reinforcement=6, message="Risque eleve")
        alert.acknowledge(manager, "Deux agents rappeles")
        alert.refresh_from_db()
        self.assertEqual(alert.status, Alert.Status.ACKNOWLEDGED)
        self.assertEqual(alert.handled_by, manager)
        self.assertIsNotNone(alert.handled_at)
        self.assertEqual(str(alert), "[Élevé] 06/01 14h00 - 16h00")
