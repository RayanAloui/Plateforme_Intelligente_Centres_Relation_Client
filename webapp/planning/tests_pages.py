"""Tests des pages Prevision, Planning et Risque (donnees fabriquees, moteur de risque reduit)."""
from datetime import date, datetime, timedelta
from io import StringIO
from unittest import mock

import numpy as np
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from crc.forecasting.probabilistic import CoxPredictive
from crc.risk.costs import DEFAULT_COSTS
from crc.risk.simulation import OperationalRiskModel
from planning import evaluation
from planning.models import (DailyForecast, Decision, IntervalForecast, PlanInterval, PlatformState, Shift,
                             StaffingPlan)

TODAY, DAY = date(2025, 1, 6), date(2025, 1, 7)
SMALL_MODEL = OperationalRiskModel(CoxPredictive(0.08, 50), np.array([0.05, 0.06]), 180, dict(DEFAULT_COSTS))


def make_day(day=DAY):
    fc = DailyForecast.objects.create(date=day, total_expected=4800, total_q10=4300, total_q90=5300, level_total=4750)
    start = datetime.combine(day, datetime.min.time())
    IntervalForecast.objects.bulk_create([IntervalForecast(
        forecast=fc, ts=start + timedelta(minutes=30 * k), expected=100.0, q01=70, q10=85, q50=100, q90=115, q99=130,
        aht_expected=300.0, explanation={"heure de la journee": 12.5, "saison": -2.0}) for k in range(48)])
    plans = {}
    for kind, status in (("actuel", "publie"), ("recommande", "brouillon")):
        p = StaffingPlan.objects.create(date=day, kind=kind, status=status, forecast=fc, cost_agents=10000,
                                        expected_loss=2000, var95=5000, es95=6500, expected_service_level=0.9,
                                        max_undercap_probability=0.08, agent_hours=360)
        PlanInterval.objects.bulk_create([PlanInterval(plan=p, ts=start + timedelta(minutes=30 * k), agents_required=20,
                                                       agents_scheduled=20, undercap_probability=0.05, expected_loss=40,
                                                       expected_service_level=0.9) for k in range(48)])
        plans[kind] = p
    rec = plans["recommande"]
    Shift.objects.create(plan=rec, start=start, end=start + timedelta(hours=12), agents=20)
    Shift.objects.create(plan=rec, start=start + timedelta(hours=12), end=start + timedelta(hours=24), agents=20)
    return fc, plans


class PagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_demo_users", stdout=StringIO())
        state = PlatformState.get()
        state.current_date = TODAY
        state.save()
        cls.fc, cls.plans = make_day()

    def login(self, user):
        self.client.login(username=user, password="Demo2024!")

    def test_forecast_page_explains_the_peak(self):
        self.login("manager")
        response = self.client.get(reverse("forecast"))
        self.assertContains(response, "Pourquoi cette prévision")
        self.assertContains(response, "Heure de la journée")
        partial = self.client.get(reverse("forecast_explain"), {"jour": "2025-01-07", "heure": "14:00"})
        self.assertContains(partial, 'value="14:00" selected')

    def test_planning_page_defaults_to_the_recommended_draft(self):
        self.login("planificateur")
        response = self.client.get(reverse("planning"))
        self.assertEqual(response.context["plan"], self.plans["recommande"])
        self.assertContains(response, "Soumettre à validation")

    def test_validation_workflow_through_the_interface(self):
        rec = self.plans["recommande"]
        self.login("planificateur")
        r = self.client.post(reverse("plan_transition", args=[rec.pk, "soumettre"]))
        self.assertIn("plan=", r["HX-Redirect"])
        self.client.post(reverse("plan_transition", args=[rec.pk, "valider"]))          # refuse : role
        rec.refresh_from_db()
        self.assertEqual(rec.status, "soumis")
        self.login("manager")
        self.client.post(reverse("plan_transition", args=[rec.pk, "valider"]))
        self.client.post(reverse("plan_transition", args=[rec.pk, "publier"]))
        rec.refresh_from_db()
        self.plans["actuel"].refresh_from_db()
        self.assertEqual((rec.status, self.plans["actuel"].status), ("publie", "remplace"))

    @mock.patch.object(evaluation, "risk_model", return_value=SMALL_MODEL)
    def test_adjusting_shifts_recomputes_coverage_and_risk(self, _):
        self.login("planificateur")
        self.client.post(reverse("plan_adjust", args=[self.plans["recommande"].pk]))
        copy = StaffingPlan.objects.get(kind="ajuste")
        self.assertEqual(copy.shifts.count(), 2)
        shift = copy.shifts.order_by("start").first()
        response = self.client.post(reverse("shift_plus", args=[copy.pk, shift.pk]))
        self.assertContains(response, "couverture et risque recalculés")
        copy.refresh_from_db()
        self.assertEqual(copy.intervals.order_by("ts").first().agents_scheduled, 21)
        self.assertTrue(copy.decisions.filter(action=Decision.Action.ADJUSTED).exists())
        self.client.post(reverse("shift_add", args=[copy.pk]), {"debut": "10:00", "duree": "4", "agents": "3"})
        self.assertEqual(copy.shifts.count(), 3)

    def test_published_or_past_plans_cannot_be_edited(self):
        self.login("manager")
        actual = self.plans["actuel"]
        shift = Shift.objects.create(plan=actual, start=datetime(2025, 1, 7, 8), end=datetime(2025, 1, 7, 16), agents=1)
        self.assertEqual(self.client.post(reverse("shift_plus", args=[actual.pk, shift.pk])).status_code, 403)

    def test_exports_are_downloadable_and_traced(self):
        self.login("manager")
        rec = self.plans["recommande"]
        xlsx = self.client.get(reverse("plan_export", args=[rec.pk, "xlsx"]))
        pdf = self.client.get(reverse("plan_export", args=[rec.pk, "pdf"]))
        self.assertTrue(xlsx["Content-Type"].startswith("application/vnd.openxml"))
        self.assertEqual(pdf.content[:4], b"%PDF")
        self.assertEqual(rec.decisions.filter(action=Decision.Action.EXPORTED).count(), 2)

    @mock.patch.object(evaluation, "loss_scenarios", return_value=np.linspace(1000, 9000, 1000))
    def test_risk_page_compares_plans(self, _):
        self.login("manager")
        response = self.client.get(reverse("risk"))
        self.assertContains(response, "Distribution des pertes")
        self.assertEqual(len(response.context["plans"]), 2)


class CoverageTests(TestCase):
    def test_night_shifts_wrap_around_the_day(self):
        start = datetime(2025, 1, 7, 22)
        shift = Shift(start=start, end=start + timedelta(hours=8), agents=4)
        cover = evaluation.coverage_from_shifts([shift], date(2025, 1, 7))
        self.assertEqual(cover.iloc[0], 4)                 # 00h00 couvert par la vacation de 22h
        self.assertEqual(cover.iloc[44], 4)                # 22h00
        self.assertEqual(cover.iloc[20], 0)                # 10h00
        self.assertEqual(cover.sum(), 4 * 16)
