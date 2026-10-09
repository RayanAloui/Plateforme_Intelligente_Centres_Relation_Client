"""Page de l'assistant IA (module 20)."""
from django.core.cache import cache
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.roles import role_required
from assistant.llm import OllamaClient
from assistant.models import Conversation
from assistant.service import answer
from portal.navigation import ALL

SUGGESTIONS = [
    "Pourquoi le risque est-il élevé demain vers 10h ?",
    "Combien d'agents faut-il en plus demain ?",
    "Quelles sont les alertes pour demain ?",
    "Comment s'est passée la journée d'aujourd'hui ?",
    "Quel effectif prévoir en 2026 ?",
    "Le modèle de prévision est-il fiable en ce moment ?",
]


def llm_status() -> dict:
    status = cache.get("ollama-status")
    if status is None:
        status = OllamaClient().status()
        cache.set("ollama-status", status, 15)
    return status


@role_required(*ALL)
def assistant_page(request, pk=None):
    conversations = Conversation.objects.filter(user=request.user)[:20]
    current = get_object_or_404(Conversation, pk=pk, user=request.user) if pk else None
    return render(request, "assistant/page.html", {
        "page_title": "Assistant IA", "conversations": conversations, "current": current,
        "messages_list": current.messages.all() if current else [], "status": llm_status(),
        "suggestions": SUGGESTIONS})


@require_POST
@role_required(*ALL)
def assistant_ask(request):
    text = request.POST.get("question", "").strip()[:500]
    pk = request.POST.get("conversation")
    conversation = get_object_or_404(Conversation, pk=pk, user=request.user) if pk else \
        Conversation.objects.create(user=request.user)
    if not text:
        return render(request, "assistant/_exchange.html", {"pair": []})
    reply = answer(conversation, text)
    question = conversation.messages.filter(role="user").last()
    response = render(request, "assistant/_exchange.html", {"pair": [question, reply], "conversation": conversation,
                                                            "new": not pk})
    if not pk:
        response["HX-Push-Url"] = reverse("assistant_conversation", args=[conversation.pk])
    return response
