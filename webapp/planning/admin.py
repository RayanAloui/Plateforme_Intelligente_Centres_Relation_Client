from django.contrib import admin

from planning.models import (DailyForecast, Decision, ModelVersion, PipelineRun, PlanInterval,
                             PlatformState, Shift, StaffingPlan)


class PlanIntervalInline(admin.TabularInline):
    model = PlanInterval
    extra = 0


class ShiftInline(admin.TabularInline):
    model = Shift
    extra = 0


class DecisionInline(admin.TabularInline):
    model = Decision
    extra = 0
    readonly_fields = ("user", "action", "comment", "created_at")


@admin.register(StaffingPlan)
class StaffingPlanAdmin(admin.ModelAdmin):
    list_display = ("date", "kind", "status", "agent_hours", "cost_agents", "expected_loss", "created_by")
    list_filter = ("status", "kind")
    date_hierarchy = "date"
    inlines = [ShiftInline, DecisionInline, PlanIntervalInline]


@admin.register(DailyForecast)
class DailyForecastAdmin(admin.ModelAdmin):
    list_display = ("date", "total_expected", "total_q10", "total_q90", "model_version")
    date_hierarchy = "date"


@admin.register(ModelVersion)
class ModelVersionAdmin(admin.ModelAdmin):
    list_display = ("version", "cutoff", "is_active", "created_at")


@admin.register(PipelineRun)
class PipelineRunAdmin(admin.ModelAdmin):
    list_display = ("kind", "target_date", "status", "started_at", "finished_at", "triggered_by")
    list_filter = ("kind", "status")


admin.site.register(PlatformState)
