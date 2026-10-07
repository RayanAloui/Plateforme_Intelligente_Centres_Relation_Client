from django.contrib import admin

from alerts.models import Alert


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("date", "start", "end", "level", "source", "status", "recommended_reinforcement")
    list_filter = ("level", "source", "status")
    date_hierarchy = "date"
