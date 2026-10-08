from datetime import date, datetime, timedelta
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import User
from planning.models import Decision, ModelVersion, PlatformState, Shift, StaffingPlan

DAY = date(2025, 1, 6)


class PlanWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_demo_users", stdout=StringIO())
        cls.manager = User.objects.get(username="manager")
        cls.planner = User.objects.get(username="planificateur")

    def make_plan(self, **kw):
        return StaffingPlan.objects.create(date=DAY, kind=StaffingPlan.Kind.RECOMMENDED, **kw)

    def test_full_lifecycle_is_audited(self):
        plan = self.make_plan()
        plan.transition("soumettre", self.planner)
        plan.transition("valider", self.manager)
        plan.transition("publier", self.manager)
        self.assertEqual(plan.status, StaffingPlan.Status.PUBLISHED)
        actions = list(plan.decisions.order_by("created_at").values_list("action", flat=True))
        self.assertEqual(actions, ["soumettre", "valider", "publier"])

    def test_planner_cannot_validate(self):
        plan = self.make_plan()
        plan.transition("soumettre", self.planner)
        self.assertFalse(plan.can("valider", self.planner))
        with self.assertRaises(ValidationError):
            plan.transition("valider", self.planner)

    def test_rejection_requires_a_reason_and_returns_to_draft(self):
        plan = self.make_plan()
        plan.transition("soumettre", self.planner)
        with self.assertRaises(ValidationError):
            plan.transition("refuser", self.manager)
        plan.transition("refuser", self.manager, comment="Trop peu d'agents a midi")
        self.assertTrue(plan.is_editable)

    def test_illegal_transition_is_refused(self):
        with self.assertRaises(ValidationError):
            self.make_plan().transition("publier", self.manager)

    def test_publishing_supersedes_the_previous_plan(self):
        first, second = self.make_plan(), self.make_plan()
        for plan in (first, second):
            plan.transition("soumettre", self.planner)
            plan.transition("valider", self.manager)
            plan.transition("publier", self.manager)
        first.refresh_from_db()
        self.assertEqual(first.status, StaffingPlan.Status.SUPERSEDED)
        self.assertTrue(first.decisions.filter(action=Decision.Action.SUPERSEDED).exists())

    def test_database_forbids_two_published_plans_the_same_day(self):
        self.make_plan(status=StaffingPlan.Status.PUBLISHED)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_plan(status=StaffingPlan.Status.PUBLISHED)

    def test_shift_must_end_after_it_starts(self):
        plan = self.make_plan()
        start = datetime(2025, 1, 6, 8)
        self.assertEqual(Shift.objects.create(plan=plan, start=start, end=start + timedelta(hours=8), agents=5).hours, 8)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Shift.objects.create(plan=plan, start=start, end=start, agents=5)


class PlatformTests(TestCase):
    def test_platform_state_is_a_singleton(self):
        PlatformState.get().current_date = DAY
        self.assertEqual(PlatformState.objects.count(), 1)
        self.assertEqual(PlatformState.get().pk, 1)

    def test_only_one_active_model(self):
        a = ModelVersion.objects.create(version="forecast_20240701", cutoff=date(2024, 7, 1), file_path="a")
        b = ModelVersion.objects.create(version="forecast_20240801", cutoff=date(2024, 8, 1), file_path="b")
        a.activate()
        b.activate()
        a.refresh_from_db()
        self.assertFalse(a.is_active)
        self.assertEqual(ModelVersion.objects.get(is_active=True), b)


# --- Cycle quotidien : execution, journal, interface ---------------------------------------------------
from unittest import mock  # noqa: E402

from django.urls import reverse  # noqa: E402
from django.utils import timezone  # noqa: E402

from planning.models import PipelineRun  # noqa: E402
from planning.services import step  # noqa: E402
from planning.tasks import STALE_AFTER, launch, running_run  # noqa: E402


class TaskRunnerTests(TestCase):
    def test_success_and_failure_are_recorded(self):
        ok = launch(PipelineRun.Kind.DAILY, None, lambda run: "Termine", background=False)
        self.assertEqual((ok.status, ok.message), (PipelineRun.Status.SUCCESS, "Termine"))

        def boom(run):
            raise RuntimeError("exports absents")
        ko = launch(PipelineRun.Kind.DAILY, None, boom, background=False)
        self.assertEqual(ko.status, PipelineRun.Status.FAILED)
        self.assertIn("exports absents", ko.message)

    def test_two_runs_never_overlap(self):
        PipelineRun.objects.create(kind=PipelineRun.Kind.DAILY)          # un traitement en cours
        self.assertIsNone(launch(PipelineRun.Kind.DAILY, None, lambda r: "", background=False))

    def test_stale_runs_are_released(self):
        run = PipelineRun.objects.create(kind=PipelineRun.Kind.DAILY)
        PipelineRun.objects.filter(pk=run.pk).update(started_at=timezone.now() - STALE_AFTER - timedelta(minutes=1))
        self.assertIsNone(running_run())
        run.refresh_from_db()
        self.assertEqual(run.status, PipelineRun.Status.FAILED)

    def test_steps_are_journaled_with_duration(self):
        run = PipelineRun.objects.create(kind=PipelineRun.Kind.DAILY)
        with step(run, "Import et nettoyage") as s:
            s["appels"] = 4200
        with self.assertRaises(ValueError), step(run, "Prevision"):
            raise ValueError
        run.refresh_from_db()
        self.assertEqual([s["statut"] for s in run.steps], ["ok", "echec"])
        self.assertEqual(run.steps[0]["appels"], 4200)
        self.assertIn("duree_s", run.steps[1])


class CycleViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_demo_users", stdout=StringIO())

    def test_only_managers_can_advance_the_platform(self):
        self.client.login(username="planificateur", password="Demo2024!")
        self.assertEqual(self.client.post(reverse("cycle_launch")).status_code, 403)

    def test_manager_launches_and_follows_the_cycle(self):
        self.client.login(username="manager", password="Demo2024!")
        fake = PipelineRun.objects.create(kind=PipelineRun.Kind.DAILY, status=PipelineRun.Status.SUCCESS,
                                          message="Journee integree", steps=[{"etape": "Import", "statut": "ok",
                                                                              "duree_s": 0.3}])
        with mock.patch("planning.views.launch", return_value=fake):
            response = self.client.post(reverse("cycle_launch"))
        self.assertContains(response, "Journee integree")
        status = self.client.get(reverse("cycle_status", args=[fake.pk]))
        self.assertEqual(status["HX-Trigger-After-Settle"], "cycle-termine")

    def test_home_explains_how_to_initialise(self):
        self.client.login(username="manager", password="Demo2024!")
        self.assertContains(self.client.get(reverse("home")), "init_platform")
