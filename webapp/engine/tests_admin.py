"""Tests des pages d'administration : parametres, modeles, utilisateurs."""
import re
from datetime import date
from decimal import Decimal
from io import StringIO
from unittest import mock

import pandas as pd
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, User
from engine.models import Parameter, ParameterChange
from planning import monitoring
from planning.models import ModelVersion, PipelineRun


class AdminBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_demo_users", stdout=StringIO())

    def login(self, user="admin"):
        self.client.login(username=user, password="Demo2024!")

    def form(self, **changes):
        values = {p.param_name: str(p.value) for p in Parameter.objects.all()}
        for name in ("risk_alpha", "alert_medium_threshold", "alert_high_threshold", "sla_target_ratio"):
            values[name] = str(float(values[name]) * 100)               # saisis en %
        values.update(changes)
        return values


class ParameterTests(AdminBase):
    def test_reserved_to_administrators(self):
        self.login("manager")
        self.assertEqual(self.client.get(reverse("settings")).status_code, 403)
        self.login()
        self.assertContains(self.client.get(reverse("settings")), "Seuil d&#x27;alerte élevée")

    def test_valid_change_is_saved_and_traced(self):
        self.login()
        self.client.post(reverse("settings_save"), self.form(alert_medium_threshold="12", comment="hiver"))
        self.assertEqual(Parameter.objects.get(pk="alert_medium_threshold").value, Decimal("0.1200"))
        change = ParameterChange.objects.get()
        self.assertEqual((change.old_value, change.new_value, change.comment), (Decimal("0.1000"), Decimal("0.1200"), "hiver"))
        self.assertEqual(change.changed_by.username, "admin")

    def test_out_of_bounds_and_inconsistent_values_are_refused(self):
        self.login()
        r = self.client.post(reverse("settings_save"), self.form(cost_agent_hour="1000"))
        self.assertContains(r, "doit être compris entre")
        r = self.client.post(reverse("settings_save"), self.form(alert_medium_threshold="30"))
        self.assertContains(r, "inférieur au seuil d&#x27;alerte élevée")
        self.assertFalse(ParameterChange.objects.exists())


class ModelMonitoringTests(AdminBase):
    def test_drift_levels(self):
        ok = pd.DataFrame({"wape": [14, 15, 14], "biais": [0, 1, -1], "couverture": 0, "couverture80": [80, 82, 79]})
        bad = ok.assign(wape=[22, 23, 24])
        self.assertEqual(monitoring.drift_status(ok, {"WAPE_%": 14.4})["level"], "ok")
        self.assertEqual(monitoring.drift_status(bad, {"WAPE_%": 14.4})["level"], "derive")
        self.assertEqual(monitoring.drift_status(ok.head(2), {})["level"], "inconnu")

    def test_models_page_and_rollback(self):
        old = ModelVersion.objects.create(version="forecast_20241201", cutoff=date(2024, 12, 1), file_path="a",
                                          metrics={"WAPE_%": 14.8})
        new = ModelVersion.objects.create(version="forecast_20250101", cutoff=date(2025, 1, 1), file_path="b",
                                          metrics={"WAPE_%": 14.4, "couverture_fourchette_80_%": 84.6})
        new.activate()
        self.login()
        self.assertContains(self.client.get(reverse("models")), "14,40 %")
        self.client.post(reverse("model_activate", args=[old.pk]))
        self.assertTrue(ModelVersion.objects.get(pk=old.pk).is_active)

    def test_retrain_runs_in_background(self):
        self.login()
        fake = PipelineRun.objects.create(kind=PipelineRun.Kind.RETRAIN)
        with mock.patch("planning.monitoring.launch", return_value=fake) as launch:
            self.assertContains(self.client.post(reverse("model_retrain")), "Réentraînement en cours")
        self.assertEqual(launch.call_args.args[0], PipelineRun.Kind.RETRAIN)


class UserManagementTests(AdminBase):
    def test_created_user_can_log_in_with_the_temporary_password(self):
        self.login()
        r = self.client.post(reverse("user_create"), {"username": "l.saidi", "first_name": "Lina",
                                                      "last_name": "Saidi", "role": Role.PLANIFICATEUR})
        password = re.search(r'id="temp-pw">([^<]+)<', r.content.decode()).group(1)
        self.client.logout()
        self.assertTrue(self.client.login(username="l.saidi", password=password))

    def test_duplicates_are_refused(self):
        self.login()
        r = self.client.post(reverse("user_create"), {"username": "manager", "role": Role.MANAGER})
        self.assertContains(r, "existe déjà")

    def test_deactivate_and_change_role(self):
        self.login()
        manager = User.objects.get(username="manager")
        self.client.post(reverse("user_update", args=[manager.pk]), {"role": Role.PLANIFICATEUR})   # case decochee
        manager.refresh_from_db()
        self.assertEqual((manager.role, manager.is_active), (Role.PLANIFICATEUR, False))

    def test_cannot_lock_out_the_last_administrator(self):
        self.login()
        admin = User.objects.get(username="admin")
        self.client.post(reverse("user_update", args=[admin.pk]), {"role": Role.MANAGER, "is_active": "on"})
        admin.refresh_from_db()
        self.assertEqual(admin.role, Role.ADMINISTRATEUR)

    def test_every_user_can_change_password(self):
        self.login("planificateur")
        r = self.client.post(reverse("password_change"), {"old_password": "Demo2024!", "new_password1": "Nouveau#2025",
                                                          "new_password2": "Nouveau#2025"})
        self.assertRedirects(r, reverse("home"))
        self.client.logout()
        self.assertTrue(self.client.login(username="planificateur", password="Nouveau#2025"))
