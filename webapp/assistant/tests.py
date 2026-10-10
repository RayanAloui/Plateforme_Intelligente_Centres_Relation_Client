from datetime import date
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import User
from assistant.facts import build_sheet, render_sheet
from assistant.guard import numbers, verify
from assistant.llm import OllamaUnavailable, Reply
from assistant.models import Conversation, Message
from assistant.service import answer
from assistant.understanding import understand
from planning.models import PlatformState
from planning.tests_pages import DAY, TODAY, make_day


class UnderstandingTests(SimpleTestCase):
    def test_risk_question_with_an_hour(self):
        q = understand("Pourquoi le risque est-il élevé demain à 14h ?", TODAY)
        self.assertEqual((q.day, q.hour), (DAY, "14:00"))
        self.assertIn("risque", q.topics)
        self.assertIn("prevision", q.topics)              # « pourquoi » : on explique avec la prevision

    def test_reinforcement_question_brings_the_risk(self):
        self.assertEqual(understand("Combien d'agents faut-il en plus ?", TODAY).topics, ["planning", "risque"])

    def test_past_day_and_long_term(self):
        self.assertEqual(understand("Et hier ?", TODAY).topics, ["historique"])
        self.assertEqual(understand("Et hier ?", TODAY).day, date(2025, 1, 5))
        q = understand("Quel effectif prévoir en 2027 ?", TODAY)
        self.assertEqual((q.topics, q.year), (["capacite"], 2027))

    def test_follow_up_keeps_the_previous_subject(self):
        self.assertEqual(understand("et à 16h30 ?", TODAY, ["risque"]).topics, ["risque"])
        self.assertEqual(understand("et à 16h30 ?", TODAY, ["risque"]).hour, "16:30")


class GuardTests(SimpleTestCase):
    def test_french_numbers_are_read(self):
        self.assertEqual(numbers("5 885 appels, 12,5 % et 3.2"), [5885.0, 12.5, 3.2])

    def test_numbers_must_come_from_the_sheet(self):
        sheet = "- Appels prévus : 5 885\n- Probabilité : 24,3 %"
        self.assertTrue(verify("Environ 5 885 appels, soit 24 % de risque.", sheet)["verified"])
        result = verify("Il faut 4 321 agents.", sheet)
        self.assertEqual(result["unknown"], ["4 321"])
        self.assertTrue(verify("Deux agents suffisent.", sheet)["verified"])


class GuardMisuseTests(SimpleTestCase):
    sheet = "- Planning actuel : 653 heures d'agents\n- Le planning recommandé utilise 67 heures d'agents de moins"

    def test_a_number_must_keep_its_unit(self):
        result = verify("Il faudrait retirer 67 agents.", self.sheet)
        self.assertFalse(result["verified"])
        self.assertIn("67 agents (dans les données : 67 heures)", result["issues"])

    def test_calculations_are_refused(self):
        self.assertIn("calcul effectué par le modèle", verify("586 - 653 = -67 heures", self.sheet + " 586")["issues"])


class FakeClient:
    def __init__(self, text=None, fail=False):
        self.text, self.fail, self.model = text, fail, "fake"

    def chat(self, messages):
        if self.fail:
            raise OllamaUnavailable("connexion refusée")
        self.messages = messages
        return Reply(self.text, "fake", 12)


class AssistantTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_demo_users", stdout=StringIO())
        state = PlatformState.get()
        state.current_date = TODAY
        state.save()
        make_day()
        cls.manager = User.objects.get(username="manager")

    def test_sheet_contains_the_facts_of_the_hour(self):
        sheet = render_sheet(build_sheet(understand("Pourquoi le risque demain à 10h ?", TODAY)))
        self.assertIn("Prévision à 10h00 : 100 appels", sheet)
        self.assertIn("Effet de l'heure de la journée", sheet)
        self.assertIn("À 10h00 avec le planning en vigueur : 20 agents", sheet)

    def test_key_points_correct_a_false_premise(self):
        sheet = build_sheet(understand("Pourquoi le risque est-il élevé demain à 10h ?", TODAY))
        points = " ".join(sheet["À retenir"])
        self.assertIn("le risque de sous-capacité est faible : 5 %", points)
        self.assertIn("Contrairement à ce que suppose la question", points)
        self.assertIn("le facteur principal est l'effet de l'heure de la journée", points)

    def test_key_points_answer_the_reinforcement_question(self):
        sheet = build_sheet(understand("Combien d'agents faut-il en plus demain ?", TODAY))
        self.assertIn("Aucun renfort n'est nécessaire", " ".join(sheet["À retenir"]))

    def test_answer_is_grounded_verified_and_stored(self):
        conv = Conversation.objects.create(user=self.manager)
        client = FakeClient("Demain, 4 800 appels sont prévus.")
        msg = answer(conv, "Combien d'appels demain ?", client)
        self.assertIn("FICHE DE DONNÉES", client.messages[-1]["content"])
        self.assertTrue(msg.context["verification"]["verified"])
        self.assertEqual(conv.messages.count(), 2)
        self.assertEqual(Conversation.objects.get().title, "Combien d'appels demain ?")

    def test_conclusion_first_and_unreliable_explanation_discarded(self):
        conv = Conversation.objects.create(user=self.manager)
        good = answer(conv, "Combien d'agents faut-il en plus demain ?",
                      FakeClient("Le planning en vigueur prévoit 360 heures d'agents."))
        self.assertTrue(good.content.startswith("Aucun renfort n'est nécessaire demain"))
        self.assertIn("360 heures d'agents", good.content)
        bad = answer(conv, "Combien d'agents faut-il en plus demain ?", FakeClient("Il faut 586 - 653 = -67 agents."))
        self.assertTrue(bad.content.startswith("Aucun renfort n'est nécessaire demain"))
        self.assertNotIn("586", bad.content)                     # explication ecartee par le garde-fou
        self.assertIn("586", bad.context["explication_ecartee"])

    def test_explanation_without_new_figures_is_not_shown(self):
        conv = Conversation.objects.create(user=self.manager)
        msg = answer(conv, "Combien d'appels demain ?", FakeClient("Cela représente 4 800 appels, à 4 800 près."))
        self.assertNotIn("à 4 800 près", msg.content)                 # ne cite que des chiffres de la conclusion
        self.assertIn("explication_redondante", msg.context)

    def test_shortfall_is_explained_in_the_conclusion(self):
        from planning.models import StaffingPlan
        plan = StaffingPlan.objects.get(kind="actuel")
        plan.intervals.filter(ts__hour=14, ts__minute=0).update(agents_scheduled=18, undercap_probability=0.09)
        points = " ".join(build_sheet(understand("Et le risque demain à 14h ?", TODAY))["À retenir"])
        self.assertIn("prévoit 2 agents de moins que l'effectif recommandé à 14h00", points)
        self.assertIn("le risque reste faible", points)

    def test_terminal_questions_do_not_clutter_conversations(self):
        with mock.patch("assistant.management.commands.ask_assistant.OllamaClient",
                        return_value=FakeClient(fail=True)):
            call_command("ask_assistant", "Combien d'appels demain ?", stdout=StringIO())
            self.assertFalse(Conversation.objects.exists())
            call_command("ask_assistant", "Combien d'appels demain ?", "--keep", stdout=StringIO())
            self.assertEqual(Conversation.objects.count(), 1)

    def test_explanation_that_only_repeats_is_not_shown(self):
        conv = Conversation.objects.create(user=self.manager)
        lead = "Aucun renfort n'est nécessaire demain : le planning en vigueur couvre le besoin"
        msg = answer(conv, "Combien d'agents faut-il en plus demain ?", FakeClient(lead + " sur toutes les demi-heures."))
        self.assertEqual(msg.content.count("Aucun renfort"), 1)

    def test_without_ollama_the_platform_still_answers_with_data(self):
        conv = Conversation.objects.create(user=self.manager)
        msg = answer(conv, "Combien d'appels demain ?", FakeClient(fail=True))
        self.assertTrue(msg.content.startswith("4 800 appels sont prévus"))        # la conclusion suffit
        self.assertIn("hors_ligne", msg.context["verification"])
        generic = answer(conv, "Quels sont les coûts ?", FakeClient(fail=True))   # pas de conclusion : la fiche
        self.assertIn("momentanément indisponible", generic.content)

    def test_page_and_first_question(self):
        self.client.login(username="manager", password="Demo2024!")
        with mock.patch("assistant.views.llm_status", return_value={"online": False, "model": "qwen2.5:3b",
                                                                     "installed": False}):
            self.assertContains(self.client.get(reverse("assistant")), "Ollama hors ligne")
        with mock.patch("assistant.service.OllamaClient", return_value=FakeClient("Il y a 4 800 appels prévus.")):
            r = self.client.post(reverse("assistant_ask"), {"question": "Combien d'appels demain ?"})
        conv = Conversation.objects.get(user=self.manager)
        self.assertEqual(r["HX-Push-Url"], reverse("assistant_conversation", args=[conv.pk]))
        self.assertContains(r, "Conclusion calculée par la plateforme")     # explication sans chiffre nouveau
        self.assertEqual(Message.objects.filter(conversation=conv).count(), 2)

    def test_conversations_are_private(self):
        other = Conversation.objects.create(user=User.objects.get(username="planificateur"))
        self.client.login(username="manager", password="Demo2024!")
        self.assertEqual(self.client.get(reverse("assistant_conversation", args=[other.pk])).status_code, 404)
