"""Memoire de la plateforme : ce qu'elle a prevu, recommande, ce qui a ete decide.

    PlatformState   : la "date du jour" de la plateforme (avancee par le cycle quotidien)
    ModelVersion    : versions du modele de prevision et leurs performances
    PipelineRun     : journal des traitements (cycle quotidien, reentrainement...)
    DailyForecast   : prevision d'une journee, emise la veille
      IntervalForecast : une demi-heure prevue, avec sa fourchette
    StaffingPlan    : un planning pour une journee, avec son cycle de vie
      PlanInterval   : besoin et couverture par demi-heure, risque associe
      Shift          : vacations (debut, fin, nombre d'agents)
      Decision       : piste d'audit de chaque action sur le planning
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from accounts.models import Role

User = settings.AUTH_USER_MODEL


class PlatformState(models.Model):
    """Singleton : la date que la plateforme considere comme "aujourd'hui"."""
    current_date = models.DateField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "état de la plateforme"

    @classmethod
    def get(cls) -> "PlatformState":
        state, _ = cls.objects.get_or_create(pk=1)
        return state


class ModelVersion(models.Model):
    version = models.CharField(max_length=40, unique=True)
    cutoff = models.DateField(help_text="Le modele n'a vu aucune donnee posterieure.")
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=False)
    file_path = models.CharField(max_length=200)
    metrics = models.JSONField(default=dict, help_text="WAPE, biais, couverture... hors echantillon")
    card = models.JSONField(default=dict, help_text="Fiche d'identite complete du modele")

    class Meta:
        ordering = ["-cutoff"]
        constraints = [models.UniqueConstraint(fields=["is_active"], condition=models.Q(is_active=True),
                                               name="un_seul_modele_actif")]

    def __str__(self):
        return self.version

    @transaction.atomic
    def activate(self):
        ModelVersion.objects.filter(is_active=True).exclude(pk=self.pk).update(is_active=False)
        self.is_active = True
        self.save(update_fields=["is_active"])


class PipelineRun(models.Model):
    class Kind(models.TextChoices):
        DAILY = "cycle_quotidien", "Cycle quotidien"
        RETRAIN = "reentrainement", "Réentraînement"
        IMPORT = "import", "Import de données"
        REPLAN = "replanification", "Replanification"

    class Status(models.TextChoices):
        RUNNING = "en_cours", "En cours"
        SUCCESS = "succes", "Succès"
        FAILED = "echec", "Échec"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    target_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    triggered_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    steps = models.JSONField(default=list, help_text="Etapes executees et leur duree")
    message = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def finish(self, status: str, message: str = ""):
        self.status, self.message, self.finished_at = status, message, timezone.now()
        self.save(update_fields=["status", "message", "finished_at"])

    @property
    def duration_seconds(self) -> float | None:
        return (self.finished_at - self.started_at).total_seconds() if self.finished_at else None


class DailyForecast(models.Model):
    """Prevision d'une journee, emise la veille avec une version donnee du modele."""
    date = models.DateField(unique=True)
    model_version = models.ForeignKey(ModelVersion, null=True, on_delete=models.SET_NULL)
    run = models.ForeignKey(PipelineRun, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    total_expected = models.FloatField()
    total_q10 = models.FloatField(null=True)
    total_q90 = models.FloatField(null=True)
    level_total = models.FloatField(null=True, help_text="Total journalier prevu par le SARIMAX")

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"Prévision du {self.date:%d/%m/%Y}"


class IntervalForecast(models.Model):
    forecast = models.ForeignKey(DailyForecast, related_name="intervals", on_delete=models.CASCADE)
    ts = models.DateTimeField()
    expected = models.FloatField()
    q01 = models.FloatField()
    q10 = models.FloatField()
    q50 = models.FloatField()
    q90 = models.FloatField()
    q99 = models.FloatField()
    aht_expected = models.FloatField()
    explanation = models.JSONField(default=dict, blank=True, help_text="Effet de chaque facteur, en %")

    class Meta:
        ordering = ["ts"]
        constraints = [models.UniqueConstraint(fields=["forecast", "ts"], name="une_prevision_par_demi_heure")]


class StaffingPlan(models.Model):
    """Un planning pour une journee. Cycle de vie :

        brouillon --soumettre--> soumis --valider--> valide --publier--> publie
                                   |--refuser--> brouillon
        Publier un planning remplace le planning publie precedent du meme jour.
    """

    class Kind(models.TextChoices):
        CURRENT = "actuel", "Planning actuel (outil WFM)"
        AI = "ia", "IA seule"
        RECOMMENDED = "recommande", "Recommandé (IA + risque)"
        ADJUSTED = "ajuste", "Ajusté manuellement"
        SCENARIO = "scenario", "Issu d'un scénario what-if"

    class Status(models.TextChoices):
        DRAFT = "brouillon", "Brouillon"
        SUBMITTED = "soumis", "Soumis à validation"
        VALIDATED = "valide", "Validé"
        PUBLISHED = "publie", "Publié"
        SUPERSEDED = "remplace", "Remplacé"

    date = models.DateField()
    kind = models.CharField(max_length=12, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    title = models.CharField(max_length=120, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, related_name="children", on_delete=models.SET_NULL,
                               help_text="Planning dont celui-ci est derive (ajustement, scenario)")
    forecast = models.ForeignKey(DailyForecast, null=True, blank=True, on_delete=models.SET_NULL)
    alpha = models.FloatField(null=True, blank=True, help_text="Risque de sous-capacite tolere")
    scenario = models.JSONField(default=dict, blank=True, help_text="Hypotheses what-if eventuelles")
    created_by = models.ForeignKey(User, null=True, blank=True, related_name="+", on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Synthese du risque (calculee par le moteur)
    agent_hours = models.FloatField(null=True)
    cost_agents = models.FloatField(null=True)
    expected_loss = models.FloatField(null=True)
    var95 = models.FloatField(null=True)
    es95 = models.FloatField(null=True)
    expected_service_level = models.FloatField(null=True)
    max_undercap_probability = models.FloatField(null=True)
    details = models.JSONField(default=dict, blank=True,
                               help_text="Vacations (solveur, ecart a l'optimum), comparaison au besoin ideal")

    class Meta:
        ordering = ["-date", "-created_at"]
        constraints = [models.UniqueConstraint(fields=["date"], condition=models.Q(status="publie"),
                                               name="un_seul_planning_publie_par_jour")]

    def __str__(self):
        return f"{self.get_kind_display()} du {self.date:%d/%m/%Y} ({self.get_status_display()})"

    @property
    def expected_total_cost(self) -> float | None:
        if self.cost_agents is None or self.expected_loss is None:
            return None
        return self.cost_agents + self.expected_loss

    @property
    def is_editable(self) -> bool:
        return self.status == self.Status.DRAFT

    # --- Cycle de vie ---------------------------------------------------------------------------
    TRANSITIONS = {
        "soumettre": (Status.DRAFT, Status.SUBMITTED, (Role.PLANIFICATEUR, Role.MANAGER)),
        "refuser": (Status.SUBMITTED, Status.DRAFT, (Role.MANAGER,)),
        "valider": (Status.SUBMITTED, Status.VALIDATED, (Role.MANAGER,)),
        "publier": (Status.VALIDATED, Status.PUBLISHED, (Role.MANAGER,)),
    }

    def can(self, action: str, user) -> bool:
        source, _, roles = self.TRANSITIONS[action]
        return self.status == source and user.has_role(*roles)

    @transaction.atomic
    def transition(self, action: str, user, comment: str = "") -> "StaffingPlan":
        if action not in self.TRANSITIONS:
            raise ValidationError(f"Action inconnue : {action}")
        source, target, roles = self.TRANSITIONS[action]
        # Verrou sur la ligne : une modification en cours (ajustement) finit avant la transition.
        self.status = StaffingPlan.objects.select_for_update().values_list("status", flat=True).get(pk=self.pk)
        if self.status != source:
            raise ValidationError(f"Impossible de {action} un planning au statut « {self.get_status_display()} ».")
        if not user.has_role(*roles):
            raise ValidationError(f"Votre rôle ne permet pas de {action} ce planning.")
        if action == "refuser" and not comment:
            raise ValidationError("Un refus doit être motivé.")
        if target == self.Status.PUBLISHED:
            for old in StaffingPlan.objects.filter(date=self.date, status=self.Status.PUBLISHED).exclude(pk=self.pk):
                old.status = self.Status.SUPERSEDED
                old.save(update_fields=["status", "updated_at"])
                Decision.objects.create(plan=old, user=user, action=Decision.Action.SUPERSEDED,
                                        comment=f"Remplacé par le planning n°{self.pk}")
        self.status = target
        self.save(update_fields=["status", "updated_at"])
        Decision.objects.create(plan=self, user=user, action=action, comment=comment)
        return self


class PlanInterval(models.Model):
    """Une demi-heure du planning : besoin, couverture par les vacations, risque."""
    plan = models.ForeignKey(StaffingPlan, related_name="intervals", on_delete=models.CASCADE)
    ts = models.DateTimeField()
    agents_required = models.PositiveSmallIntegerField(help_text="Besoin issu de l'optimisation")
    agents_scheduled = models.PositiveSmallIntegerField(help_text="Agents couverts par les vacations")
    undercap_probability = models.FloatField(null=True)
    expected_loss = models.FloatField(null=True)
    expected_service_level = models.FloatField(null=True)

    class Meta:
        ordering = ["ts"]
        constraints = [models.UniqueConstraint(fields=["plan", "ts"], name="une_ligne_par_demi_heure")]

    @property
    def gap(self) -> int:
        """Ecart couverture - besoin (negatif = manque d'agents)."""
        return self.agents_scheduled - self.agents_required


class Shift(models.Model):
    """Une vacation : `agents` agents travaillent de `start` a `end`."""
    plan = models.ForeignKey(StaffingPlan, related_name="shifts", on_delete=models.CASCADE)
    start = models.DateTimeField()
    end = models.DateTimeField()
    agents = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["start", "end"]
        constraints = [models.CheckConstraint(condition=models.Q(end__gt=models.F("start")),
                                              name="vacation_fin_apres_debut")]

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600


class Decision(models.Model):
    """Piste d'audit : chaque action sur un planning, par qui, quand, pourquoi."""

    class Action(models.TextChoices):
        CREATED = "cree", "Créé"
        ADJUSTED = "ajuste", "Ajusté"
        SUBMITTED = "soumettre", "Soumis"
        REJECTED = "refuser", "Refusé"
        VALIDATED = "valider", "Validé"
        PUBLISHED = "publier", "Publié"
        SUPERSEDED = "remplace", "Remplacé"
        REINFORCED = "renfort", "Renfort appliqué"
        EXPORTED = "export", "Exporté"

    plan = models.ForeignKey(StaffingPlan, related_name="decisions", on_delete=models.CASCADE)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=12, choices=Action.choices)
    comment = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
