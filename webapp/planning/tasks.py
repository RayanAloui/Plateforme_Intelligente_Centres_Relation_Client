"""Execution des traitements en arriere-plan, sans infrastructure supplementaire.

Un fil d'execution unique traite les demandes une par une : deux cycles ne peuvent jamais
tourner en meme temps. L'avancement est ecrit en base (PipelineRun), l'interface le relit.
"""
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.db import connections, transaction
from django.utils import timezone

from planning.models import PipelineRun

log = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="plateforme")
STALE_AFTER = timedelta(minutes=30)


def running_run() -> PipelineRun | None:
    """Traitement en cours (les traitements bloques depuis plus de 30 min sont declares en echec)."""
    stale = PipelineRun.objects.filter(status=PipelineRun.Status.RUNNING,
                                       started_at__lt=timezone.now() - STALE_AFTER)
    for run in stale:
        run.finish(PipelineRun.Status.FAILED, "Interrompu (delai depasse)")
    return PipelineRun.objects.filter(status=PipelineRun.Status.RUNNING).first()


def launch(kind: str, user, func, background: bool = True) -> PipelineRun | None:
    """Cree le journal du traitement et l'execute. Renvoie None si un traitement est deja en cours."""
    with transaction.atomic():
        if running_run():
            return None
        run = PipelineRun.objects.create(kind=kind, triggered_by=user)
    if background:
        _executor.submit(_in_thread, run.pk, func)
    else:
        _execute(run.pk, func)
        run.refresh_from_db()
    return run


def _in_thread(run_id: int, func) -> None:
    """Le fil d'arriere-plan a ses propres connexions : on les ferme quand il a fini."""
    try:
        _execute(run_id, func)
    finally:
        connections.close_all()


def _execute(run_id: int, func) -> None:
    run = PipelineRun.objects.get(pk=run_id)
    try:
        message = func(run) or ""
        run.finish(PipelineRun.Status.SUCCESS, message)
    except Exception as exc:
        log.error("Echec du traitement %s : %s", run_id, traceback.format_exc())
        run.finish(PipelineRun.Status.FAILED, f"{type(exc).__name__} : {exc}")
