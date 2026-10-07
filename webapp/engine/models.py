"""Acces Django aux tables du moteur (schemas ref et core).

Ces tables appartiennent au moteur `crc` : Django ne les cree pas et ne les modifie pas
(managed = False). Il les lit, et pour les parametres, les met a jour depuis l'interface.
Le moteur relit ces memes lignes (crc.risk.costs.load_costs) : une seule source de verite.
"""
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models


class CalendarSlot(models.Model):
    ts = models.DateTimeField(primary_key=True)
    date = models.DateField()
    day_of_week = models.SmallIntegerField()
    period_index = models.SmallIntegerField()
    is_weekend = models.BooleanField()
    is_holiday = models.BooleanField()
    holiday_name = models.CharField(max_length=80, null=True)
    is_school_holiday = models.BooleanField()
    season = models.CharField(max_length=10)

    class Meta:
        managed = False
        db_table = '"ref"."calendar"'
        ordering = ["ts"]


class Event(models.Model):
    event_id = models.AutoField(primary_key=True)
    start_ts = models.DateTimeField()
    end_ts = models.DateTimeField()
    event_type = models.CharField(max_length=40)
    intensity = models.DecimalField(max_digits=5, decimal_places=2)
    description = models.TextField(null=True)

    class Meta:
        managed = False
        db_table = '"ref"."events"'
        ordering = ["start_ts"]


class IntervalMetric(models.Model):
    """Une demi-heure observee et nettoyee (core.interval_metrics)."""
    ts = models.DateTimeField(primary_key=True)
    offered = models.IntegerField()
    answered = models.IntegerField()
    abandoned = models.IntegerField()
    avg_wait_seconds = models.DecimalField(max_digits=8, decimal_places=2)
    avg_handle_seconds = models.DecimalField(max_digits=8, decimal_places=2)
    agents_scheduled = models.SmallIntegerField()
    agents_present = models.SmallIntegerField()
    agents_absent = models.SmallIntegerField()
    service_level = models.DecimalField(max_digits=5, decimal_places=4)
    abandon_rate = models.DecimalField(max_digits=5, decimal_places=4)
    occupancy = models.DecimalField(max_digits=5, decimal_places=4)
    csat_mean = models.DecimalField(max_digits=4, decimal_places=3, null=True)
    csat_responses = models.SmallIntegerField()
    is_imputed = models.BooleanField()
    imputed_columns = ArrayField(models.TextField(), null=True)

    class Meta:
        managed = False
        db_table = '"core"."interval_metrics"'
        ordering = ["ts"]


class Parameter(models.Model):
    """Parametre de la plateforme (ref.cost_parameters), lu par le moteur."""
    param_name = models.CharField(max_length=50, primary_key=True)
    value = models.DecimalField(max_digits=12, decimal_places=4)
    unit = models.CharField(max_length=30)
    source = models.TextField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = '"ref"."cost_parameters"'
        ordering = ["param_name"]

    def __str__(self):
        return f"{self.param_name} = {self.value} {self.unit}"


class ParameterChange(models.Model):
    """Historique des modifications de parametres : qui, quand, avant, apres."""
    param_name = models.CharField(max_length=50)
    old_value = models.DecimalField(max_digits=12, decimal_places=4, null=True)
    new_value = models.DecimalField(max_digits=12, decimal_places=4)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    changed_at = models.DateTimeField(auto_now_add=True)
    comment = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-changed_at"]
