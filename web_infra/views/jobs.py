"""Durable job execution, retry, and immutable result views."""

from django.db import OperationalError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.vary import vary_on_headers

from foundation.contracts.errors import ArtifactError, CanonicalizationError
from services.scientific import execute_scientific_job, verify_scientific_result
from services.workflows import DatabaseBusy, InvalidTransition, execute_job, requeue_job
from web_infra.caching.responses import cached_result_response
from web_infra.middleware.tracing import mark_trace
from workflows.models import Job


@never_cache
@require_GET
def job_detail(request: HttpRequest, job_id) -> HttpResponse:
    mark_trace(request, "view.job_detail")
    job = get_object_or_404(
        Job.objects.select_related("workflow", "admission__investigation__research_run"), pk=job_id
    )
    return render(request, "workflows/job_detail.html", {"job": job})


def _execution_error(request: HttpRequest, job_id, exc) -> HttpResponse:
    try:
        job = Job.objects.get(pk=job_id)
    except OperationalError:
        return HttpResponse(
            "The SQLite state transition is still committing; retry the request.", status=503
        )
    except Job.DoesNotExist:
        return HttpResponse("Job not found.", status=404)
    return render(
        request,
        "workflows/partials/job_panel.html",
        {"job": job, "action_error": str(exc)},
        status=503 if isinstance(exc, DatabaseBusy) else 409,
    )


@require_POST
def job_execute(request: HttpRequest, job_id) -> HttpResponse:
    mark_trace(request, "view.job_execute")
    try:
        job = execute_job(job_id)
    except (DatabaseBusy, InvalidTransition) as exc:
        return _execution_error(request, job_id, exc)
    return render(request, "workflows/partials/job_panel.html", {"job": job})


@require_POST
def scientific_job_execute(request: HttpRequest, job_id) -> HttpResponse:
    mark_trace(request, "view.scientific_job_execute")
    try:
        job = execute_scientific_job(job_id)
    except (DatabaseBusy, InvalidTransition) as exc:
        return _execution_error(request, job_id, exc)
    return render(request, "workflows/partials/job_panel.html", {"job": job})


@require_POST
def job_retry(request: HttpRequest, job_id) -> HttpResponse:
    mark_trace(request, "view.job_retry")
    try:
        job = requeue_job(job_id)
    except InvalidTransition as exc:
        job = get_object_or_404(Job, pk=job_id)
        return render(
            request,
            "workflows/partials/job_panel.html",
            {"job": job, "action_error": str(exc)},
            status=409,
        )
    return render(request, "workflows/partials/job_panel.html", {"job": job})


@vary_on_headers("HX-Request")
@require_GET
def job_result(request: HttpRequest, job_id) -> HttpResponse:
    mark_trace(request, "view.job_result")
    job = get_object_or_404(Job, pk=job_id)
    if job.state != Job.State.SUCCEEDED:
        return HttpResponse("A successful immutable result is not available.", status=409)
    if job.admission_id:
        try:
            verify_scientific_result(job)
        except (InvalidTransition, ArtifactError, CanonicalizationError):
            return HttpResponse(
                "The authoritative result artifact failed verification.", status=409
            )
    return cached_result_response(request, job)
