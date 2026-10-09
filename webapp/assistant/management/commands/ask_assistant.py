"""Poser une question a l'assistant depuis le terminal (pour tester le modele local).

    python webapp/manage.py ask_assistant "Pourquoi le risque est-il eleve demain a 10h ?"
"""
from django.core.management.base import BaseCommand

from accounts.models import User
from assistant.llm import OllamaClient
from assistant.models import Conversation
from assistant.service import answer


class Command(BaseCommand):
    help = "Pose une question a l'assistant et affiche la reponse, sa verification et les donnees utilisees."

    def add_arguments(self, parser):
        parser.add_argument("question")
        parser.add_argument("--model", help="Modele Ollama a utiliser (par defaut : OLLAMA_MODEL)")

    def handle(self, *args, **options):
        user = User.objects.filter(is_active=True).order_by("pk").first()
        conversation = Conversation.objects.create(user=user, title="[terminal] " + options["question"][:60])
        msg = answer(conversation, options["question"], OllamaClient(model=options["model"]))
        v = msg.context["verification"]
        self.stdout.write(self.style.MIGRATE_HEADING("Réponse") + f"  ({msg.model_name or 'hors ligne'}, {msg.latency_ms or 0} ms)")
        self.stdout.write(msg.content)
        if msg.context.get("explication_ecartee"):
            self.stdout.write(self.style.WARNING(f"\n(Explication du modèle écartée par le garde-fou : "
                                                 f"« {msg.context['explication_ecartee']} »)"))
        problems = [f"chiffres absents des données : {', '.join(v['unknown'])}"] if v["unknown"] else []
        problems += v.get("issues", [])
        status = "vérifiée" if v["verified"] else "problèmes détectés : " + " ; ".join(problems)
        self.stdout.write(self.style.SUCCESS(f"\nVérification : {status}") if v["verified"] else self.style.ERROR(f"\nVérification : {status}"))
        self.stdout.write(self.style.MIGRATE_HEADING("\nDonnées utilisées"))
        for title, lines in msg.context["fiche"].items():
            self.stdout.write(f"[{title}]")
            for line in lines:
                self.stdout.write(f"  - {line}")
