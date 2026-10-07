from django.contrib import admin

from engine.models import Event, Parameter, ParameterChange


@admin.register(Parameter)
class ParameterAdmin(admin.ModelAdmin):
    list_display = ("param_name", "value", "unit", "updated_at")


@admin.register(ParameterChange)
class ParameterChangeAdmin(admin.ModelAdmin):
    list_display = ("param_name", "old_value", "new_value", "changed_by", "changed_at")
    readonly_fields = [f.name for f in ParameterChange._meta.fields]


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("start_ts", "end_ts", "event_type", "intensity")
    list_filter = ("event_type",)
