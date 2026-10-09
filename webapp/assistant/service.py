"""L'assistant : comprendre, rassembler les faits, faire rediger, verifier."""
from django.utils import timezone

from assistant.facts import build_sheet, render_sheet
from assistant.guard import verify
from assistant.llm import OllamaClient, OllamaUnavailable
from assistant.models import Conversation, Message
from assistant.understanding import understand
from planning.selectors import platform_today

SYSTEM_PROMPT = """Tu es l'assistant de pilotage d'un centre de relation client.
Tu réponds en français, de façon claire et concise (6 phrases au maximum), à un manager.

Règles absolues :
1. Tu n'utilises QUE les informations de la FICHE DE DONNÉES fournie. Tu ne dois jamais inventer, estimer ou calculer un chiffre absent de la fiche.
2. Tu recopies les nombres exactement comme dans la fiche, avec leur unité.
3. Si la fiche ne permet pas de répondre, dis-le simplement et indique la page de la plateforme à consulter (Prévision, Planning, Risque, Alertes, What-if, Historique, Capacité).
4. Tu expliques le « pourquoi » à partir des facteurs et des chiffres de la fiche, sans jargon inutile.
5. Pas de tableau, pas de titre : quelques phrases ou une courte liste."""

PAGES = {"prevision": "Prévision", "planning": "Planning", "risque": "Risque", "alertes": "Alertes",
         "historique": "Historique", "capacite": "Capacité", "modele": "Modèles", "parametres": "Paramètres"}


def fallback_answer(sheet: dict) -> str:
    """Sans modele de langue : la fiche elle-meme, lisible."""
    lines = ["L'assistant IA est momentanément indisponible. Voici les données de la plateforme utiles à votre question :"]
    for title, items in sheet.items():
        lines.append(f"\n{title} :")
        lines.extend(f"• {item}" for item in items)
    return "\n".join(lines)


def answer(conversation: Conversation, text: str, client: OllamaClient | None = None) -> Message:
    client = client or OllamaClient()
    previous = conversation.messages.filter(role=Message.Role.ASSISTANT).last()
    question = understand(text, platform_today(), (previous.context or {}).get("themes") if previous else None)
    sections = build_sheet(question)
    sheet = render_sheet(sections)

    Message.objects.create(conversation=conversation, role=Message.Role.USER, content=text)
    history = [{"role": m.role, "content": m.content} for m in conversation.messages.order_by("-created_at")[1:5]][::-1]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history,
                {"role": "user", "content": f"FICHE DE DONNÉES (seule source autorisée) :\n{sheet}\n\nQUESTION : {text}"}]
    context = {"themes": question.topics, "jour": question.day.isoformat() if question.day else None,
               "heure": question.hour, "fiche": sections, "pages": [PAGES[t] for t in question.topics if t in PAGES]}
    try:
        reply = client.chat(messages)
        content, model, latency = reply.text, reply.model, reply.latency_ms
        context["verification"] = verify(content, sheet, text)
    except OllamaUnavailable as exc:
        content, model, latency = fallback_answer(sections), "", None
        context["verification"] = {"verified": True, "numbers": 0, "unknown": [], "hors_ligne": str(exc)[:200]}

    message = Message.objects.create(conversation=conversation, role=Message.Role.ASSISTANT, content=content,
                                     context=context, model_name=model, latency_ms=latency)
    if not conversation.title:
        conversation.title = text[:80]
    conversation.updated_at = timezone.now()
    conversation.save(update_fields=["title", "updated_at"])
    return message
