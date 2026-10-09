"""Tests des pages Alertes, What-if, Historique et Capacite."""
from datetime import datetime
from io import StringIO
from unittest import mock

import numpy as np
import pandas as pd
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.urls import reverse

import crc.optim.shifts as shifts_module
from alerts.models import Alert
from alerts.services import realign_alerts
from planning import evaluation, insights, scenarios
from planning.models import PlatformState, StaffingPlan
from planning.tests_pages import DAY, SMALL_MODEL, TODAY, make_day


class E2Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_demo_users", stdout=StringIO())
        state = PlatformState.get()
        state.current_date = TODAY
        state.save()
        cls.fc, cls.plans = make_day()

    def setUp(self):
        cache.clear()

    def login(self, user):
        self.client.login(username=user, password="Demo2024!")


class AlertCenterTests(E2Base):
    def setUp(self):
        super().setUp()
        self.alert = Alert.objects.create(date=DAY, start=datetime(2025, 1, 7, 14), end=datetime(2025, 1, 7, 16),
                                          level=Alert.Level.HIGH, source=Alert.Source.RISK, plan=self.plans["actuel"],
                                          undercap_probability=0.24, expected_loss=620, recommended_reinforcement=6,
                                          message="Risque élevé détecté")

    def test_list_shows_structured_alert_and_link_to_recommendation(self):
        self.login("manager")
        response = self.client.get(reverse("alerts"))
        self.assertContains(response, "+6 agents")
        self.assertContains(response, f"plan={self.plans['recommande'].pk}")
        self.assertContains(self.client.get(reverse("home")), "bg-rose-500")       # pastille du menu

    def test_acknowledge_then_resolve(self):
        self.login("planificateur")
        r = self.client.post(reverse("alert_handle", args=[self.alert.pk, "prendre"]))
        self.assertContains(r, "Prise en compte")
        self.client.post(reverse("alert_handle", args=[self.alert.pk, "resoudre"]), {"comment": "2 agents rappelés"})
        self.alert.refresh_from_db()
        self.assertEqual((self.alert.status, self.alert.handling_comment), ("resolue", "2 agents rappelés"))

    def test_publishing_a_plan_realigns_the_alerts(self):
        rec = self.plans["recommande"]
        rec.intervals.filter(ts__hour=10).update(undercap_probability=0.3, agents_required=25)
        created = realign_alerts(rec, None)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, "resolue")
        new = Alert.objects.filter(plan=rec)
        self.assertEqual((created, new.count()), (1, 1))
        self.assertEqual(new.first().recommended_reinforcement, 5)


class WhatIfTests(E2Base):
    @mock.patch.object(evaluation, "risk_model", return_value=SMALL_MODEL)
    def test_simulation_shows_consequences(self, _):
        self.login("manager")
        response = self.client.post(reverse("whatif_run"), {"volume": "20", "absence": "0", "budget": "0", "alpha": "0.05"})
        self.assertContains(response, "Scénario : volume +20 %")
        self.assertGreater(response.context["delta"]["heures_agents"], 0)
        self.assertContains(response, "Transformer en planning")
        cut = self.client.post(reverse("whatif_run"), {"budget": "15"})
        self.assertNotContains(cut, "Transformer en planning")

    @mock.patch.object(evaluation, "risk_model", return_value=SMALL_MODEL)
    def test_scenario_becomes_a_draft_plan_with_shifts(self, _):
        self.login("planificateur")
        with mock.patch.object(shifts_module, "DETERMINISTIC_TIME", 0.5):
            r = self.client.post(reverse("whatif_convert"), {"volume": "10", "alpha": "0.05"})
        plan = StaffingPlan.objects.get(kind=StaffingPlan.Kind.SCENARIO)
        self.assertIn(f"plan={plan.pk}", r["HX-Redirect"])
        self.assertEqual(plan.status, "brouillon")
        self.assertTrue(plan.shifts.exists())
        self.assertEqual(plan.scenario["description"], "volume +10 %")
        self.assertIsNotNone(plan.expected_loss)

    def test_reading_scenario_is_bounded(self):
        s = scenarios.read_scenario({"volume": "900", "absence": "-5", "alpha": "abc"})
        self.assertEqual((s.volume_factor, s.extra_absence, s.alpha), (2.0, 0.0, 0.05))


class HistoryAndCapacityTests(E2Base):
    def test_history_compares_with_reality(self):
        state = PlatformState.get()
        state.current_date = DAY                       # la journee planifiee est maintenant realisee
        state.save()
        with connection.cursor() as cur:
            for k, ts in enumerate(pd.date_range(DAY, periods=48, freq="30min")):
                cur.execute("INSERT INTO ref.calendar VALUES (%s, %s, 2025, 1, 2, 1, 'Mardi', %s, %s, %s, false, false, "
                            "NULL, false, 'Hiver')", [ts, DAY, ts.hour, ts.minute, k])
                cur.execute("INSERT INTO core.interval_metrics VALUES (%s, 110, 104, 6, 15, 300, 21, 20, 1, 0.86, "
                            "0.05, 0.8, NULL, 0, false, NULL)", [ts])
        self.login("manager")
        with mock.patch.object(evaluation, "risk_model", return_value=SMALL_MODEL):
            response = self.client.get(reverse("history"))
        row = response.context["rows"][0]
        self.assertEqual(row["reel"], 48 * 110)
        self.assertIn("wfm", row["outcome"])
        self.assertContains(response, "Gain réalisé cumulé")

    def test_capacity_page_translates_volumes_into_fte(self):
        months = pd.date_range("2025-01-01", periods=24, freq="MS")
        plan = pd.DataFrame({c: np.linspace(100, 120, 24) for c in (
            "p025", "p10", "p50", "p90", "p975", "etp_p10", "etp_p50", "etp_p90", "budget_p50", "budget_p90")},
            index=months)
        fake = {"monthly": pd.DataFrame({"total": [1.0, 2.0]}, index=pd.date_range("2024-11-01", periods=2, freq="MS")),
                "plan": plan, "reliability": pd.DataFrame({"erreur_moyenne_pct": [3.1], "couverture_80_pct": [83.0],
                                                           "essais": [12]}, index=pd.Index([1], name="horizon")),
                "ratio": 0.12, "ratio_source": "test", "absence": 0.06}
        self.login("manager")
        with mock.patch.object(insights, "capacity_data", return_value=fake):
            response = self.client.get(reverse("capacity"), {"horizon": "36"})
        self.assertContains(response, "Fiabilité mesurée")
        self.assertTrue(response.context["far_horizon"])
