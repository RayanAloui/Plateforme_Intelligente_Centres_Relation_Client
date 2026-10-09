"""L'assistant : comprendre, rassembler les faits, faire rediger, verifier."""
import re

from django.utils import timezone

from assistant.facts import build_sheet, render_sheet
from assistant.guard import verify
from assistant.llm import OllamaClient, OllamaUnavailable
from assistant.models import Conversation, Message
from assistant.understanding import understand
from planning.selectors import platform_today

SYSTEM_PROMPT = """Tu es l'assistant de pilotage d'un centre de relation client. Tu écris en français pour un manager.

Une CONCLUSION, calculée par la plateforme, sera affichée avant ton texte. Ton rôle est d'écrire
1 à 2 phrases d'EXPLICATION complémentaire, à partir de la FICHE DE DONNÉES.

Règles absolues :
1. Ne répète pas la conclusion et ne la contredis jamais.
2. N'utilise que les informations de la fiche. Aucun calcul (pas de soustraction, pas de « = »), aucune estimation.
3. Recopie chaque nombre avec son unité exacte. Ne confonds jamais heures d'agents, agents, appels, ETP, euros et pourcentages.
4. Un effet négatif fait baisser la prévision, un effet positif la fait monter.
5. Si tu n'as rien d'utile à ajouter, écris seulement : « Le détail est disponible dans la page indiquée. »
6. Pas de titre, pas de liste, pas de tableau."""

FREE_PROMPT = """Tu es l'assistant de pilotage d'un centre de relation client. Tu réponds en français à un manager,
en 4 phrases au maximum, UNIQUEMENT à partir de la FICHE DE DONNÉES. Aucun calcul, aucune estimation ; chaque nombre
avec son unité exacte. Si la fiche ne permet pas de répondre, dis-le et indique la page de la plateforme à consulter
(Prévision, Planning, Risque, Alertes, What-if, Historique, Capacité). Pas de titre ni de tableau."""

PAGES = {"prevision": "Prévision", "planning": "Planning", "risque": "Risque", "alertes": "Alertes",
         "historique": "Historique", "capacite": "Capacité", "modele": "Modèles", "parametres": "Paramètres"}


def fallback_answer(sheet: dict) -> str:
    """Sans modele de langue : la fiche elle-meme, lisible."""
    lines = ["L'assistant IA est momentanément indisponible. Voici les données de la plateforme utiles à votre question :"]
    for title, items in sheet.items():
        lines.append(f"\n{title} :")
        lines.extend(f"• {item}" for item in items)
    return "\n".join(lines)


def redundant(explanation: str, lead: str) -> bool:
    """L'explication ne fait que repeter la conclusion (mots en commun) : inutile de l'afficher."""
    words = lambda t: {w for w in re.findall(r"\w{4,}", t.lower())}
    e, c = words(explanation), words(lead)
    return bool(e) and len(e & c) / len(e) > 0.7


def lead_text(points: list[str]) -> str:
    return " ".join(p[0].upper() + p[1:] + ("" if p.endswith(".") else ".") for p in points)


def answer(conversation: Conversation, text: str, client: OllamaClient | None = None) -> Message:
    """Reponse en deux temps : la conclusion, calculee par la plateforme et affichee telle quelle,
    puis une explication redigee par le modele, publiee seulement si le garde-fou la valide."""
    client = client or OllamaClient()
    previous = conversation.messages.filter(role=Message.Role.ASSISTANT).last()
    question = understand(text, platform_today(), (previous.context or {}).get("themes") if previous else None)
    sections = build_sheet(question)
    sheet = render_sheet(sections)
    lead = lead_text(sections.get("À retenir", []))

    Message.objects.create(conversation=conversation, role=Message.Role.USER, content=text)
    context = {"themes": question.topics, "jour": question.day.isoformat() if question.day else None,
               "heure": question.hour, "fiche": sections, "pages": [PAGES[t] for t in question.topics if t in PAGES],
               "conclusion": lead}
    if lead:
        prompt = (f"FICHE DE DONNÉES :\n{sheet}\n\nQUESTION DU MANAGER : {text}\n\n"
                  f"CONCLUSION DÉJÀ AFFICHÉE : {lead}\n\nÉcris l'explication complémentaire.")
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
    else:
        history = [{"role": m.role, "content": m.content}
                   for m in conversation.messages.order_by("-created_at")[1:5]][::-1]
        messages = [{"role": "system", "content": FREE_PROMPT}, *history,
                    {"role": "user", "content": f"FICHE DE DONNÉES :\n{sheet}\n\nQUESTION : {text}"}]
    try:
        reply = client.chat(messages)
        model, latency = reply.model, reply.latency_ms
        check = verify(reply.text, sheet, text)
        if lead and not check["verified"]:
            # L'explication est ecartee : la conclusion de la plateforme reste juste et suffit.
            context["explication_ecartee"] = reply.text
            content = lead
        elif lead and redundant(reply.text, lead):
            context["explication_redondante"] = reply.text
            content = lead
        else:
            content = f"{lead}\n\n{reply.text}".strip() if lead else reply.text
        context["verification"] = check
    except OllamaUnavailable as exc:
        content = lead or fallback_answer(sections)
        model, latency = "", None
        context["verification"] = {"verified": True, "numbers": 0, "unknown": [], "issues": [],
                                   "hors_ligne": str(exc)[:200]}

    message = Message.objects.create(conversation=conversation, role=Message.Role.ASSISTANT, content=content,
                                     context=context, model_name=model, latency_ms=latency)
    if not conversation.title:
        conversation.title = text[:80]
    conversation.updated_at = timezone.now()
    conversation.save(update_fields=["title", "updated_at"])
    return message
