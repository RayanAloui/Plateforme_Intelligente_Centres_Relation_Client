"""Alertes graduees (module 18) et leur traitement."""
from django.conf import settings
from django.db import models
from django.utils import timezone


class Alert(models.Model):
    class Level(models.IntegerChoices):
        LOW = 0, "Faible"
        MEDIUM = 1, "Moyen"
        HIGH = 2, "Élevé"

    class Source(models.TextChoices):
        RISK = "risque", "Risque prévu"
        ANOMALY = "anomalie", "Anomalie constatée"

    class Status(models.TextChoices):
        NEW = "nouvelle", "Nouvelle"
        ACKNOWLEDGED = "prise_en_compte", "Prise en compte"
        RESOLVED = "resolue", "Résolue"

    date = models.DateField()
    start = models.DateTimeField()
    end = models.DateTimeField()
    level = models.IntegerField(choices=Level.choices)
    source = models.CharField(max_length=10, choices=Source.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW)
    plan = models.ForeignKey("planning.StaffingPlan", null=True, blank=True, related_name="alerts",
                             on_delete=models.SET_NULL)
    undercap_probability = models.FloatField(null=True)
    expected_loss = models.FloatField(null=True)
    recommended_reinforcement = models.PositiveSmallIntegerField(default=0)
    observed_volume = models.FloatField(null=True, help_text="Pour une anomalie")
    expected_volume = models.FloatField(null=True)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    handled_at = models.DateTimeField(null=True, blank=True)
    handling_comment = models.TextField(blank=True)

    class Meta:
        ordering = ["-level", "start"]
        indexes = [models.Index(fields=["date", "status"])]

    def __str__(self):
        return f"[{self.get_level_display()}] {self.start:%d/%m %Hh%M} - {self.end:%Hh%M}"

    def acknowledge(self, user, comment: str = ""):
        self._handle(self.Status.ACKNOWLEDGED, user, comment)

    def resolve(self, user, comment: str = ""):
        self._handle(self.Status.RESOLVED, user, comment)

    def _handle(self, status, user, comment):
        self.status, self.handled_by, self.handled_at = status, user, timezone.now()
        if comment:
            self.handling_comment = comment
        self.save(update_fields=["status", "handled_by", "handled_at", "handling_comment"])
