"""Conversations avec l'assistant IA (module 20)."""
from django.conf import settings
from django.db import models


class Conversation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="conversations", on_delete=models.CASCADE)
    title = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]


class Message(models.Model):
    class Role(models.TextChoices):
        USER = "user", "Utilisateur"
        ASSISTANT = "assistant", "Assistant"

    conversation = models.ForeignKey(Conversation, related_name="messages", on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    context = models.JSONField(default=dict, blank=True, help_text="Donnees de la plateforme fournies au modele")
    model_name = models.CharField(max_length=60, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
