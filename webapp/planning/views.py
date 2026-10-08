"""Pilotage du cycle quotidien depuis l'interface."""
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from accounts.models import Role
from accounts.roles import role_required
from planning import services
from planning.models import PipelineRun
from planning.tasks import launch, running_run
from portal.navigation import ALL


@require_POST
@role_required(Role.MANAGER)
def cycle_launch(request):
    """Mode demonstration : faire avancer la plateforme d'une journee."""
    if not settings.DEMO_MODE:
        raise PermissionDenied
    run = launch(PipelineRun.Kind.DAILY, request.user, services.run_daily_cycle)
    return render(request, "planning/_cycle_status.html", {"run": run or running_run(), "already": run is None})


@role_required(*ALL)
def cycle_status(request, pk):
    run = get_object_or_404(PipelineRun, pk=pk)
    response = render(request, "planning/_cycle_status.html", {"run": run})
    if run.status == PipelineRun.Status.SUCCESS:
        response["HX-Trigger-After-Settle"] = "cycle-termine"
    return response
