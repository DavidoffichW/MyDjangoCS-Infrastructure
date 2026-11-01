"""Version-one read state, admit investigation, and read result endpoints."""

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from foundation.contracts.canonical import parse_json_strict
from foundation.contracts.errors import (
    AdmissionError,
    ArtifactError,
    CanonicalizationError,
    FoundationError,
)
from services.scientific import (
    admit_investigation,
    load_state_by_identity,
    verify_scientific_result,
)
from services.workflows import IdempotencyConflict, InvalidTransition
from workflows.models import Job, ResearchRun

from .errors import API_VERSION, api_error


@require_GET
def api_state(request: HttpRequest, run_id) -> JsonResponse:
    research_run = ResearchRun.objects.filter(pk=run_id).first()
    if research_run is None:
        return api_error("RUN_NOT_FOUND", "Research run was not found.", 404)
    try:
        state = load_state_by_identity(research_run.state_identity)
    except (KeyError, ArtifactError, FoundationError):
        return api_error("STATE_UNAVAILABLE", "Verified state is unavailable.", 409)
    return JsonResponse({"api_version": API_VERSION, "data": state.to_dict(), "ok": True})


@require_POST
def api_admit(request: HttpRequest, run_id) -> JsonResponse:
    research_run = ResearchRun.objects.filter(pk=run_id).first()
    if research_run is None:
        return api_error("RUN_NOT_FOUND", "Research run was not found.", 404)
    try:
        envelope = parse_json_strict(request.body)
        if not isinstance(envelope, dict) or set(envelope) != {"declaration", "idempotency_key"}:
            return api_error("INVALID_ENVELOPE", "Request envelope fields are invalid.", 400)
        result = admit_investigation(
            research_run, envelope["declaration"], envelope["idempotency_key"]
        )
    except CanonicalizationError:
        return api_error("INVALID_JSON", "Request is not valid restricted JSON.", 400)
    except AdmissionError as exc:
        return api_error(exc.code, str(exc), 422)
    except IdempotencyConflict as exc:
        return api_error("IDEMPOTENCY_CONFLICT", str(exc), 409)
    return JsonResponse(
        {
            "api_version": API_VERSION,
            "data": {
                "duplicate": result.duplicate,
                "job_id": str(result.job.id),
                "state": result.job.state,
            },
            "ok": True,
        },
        status=200 if result.duplicate else 201,
    )


@require_GET
def api_job_result(request: HttpRequest, job_id) -> JsonResponse:
    job = Job.objects.filter(pk=job_id).first()
    if job is None:
        return api_error("JOB_NOT_FOUND", "Job was not found.", 404)
    if not job.admission_id or job.state != Job.State.SUCCEEDED:
        return api_error("RESULT_UNAVAILABLE", "Verified scientific result is unavailable.", 409)
    try:
        payload = verify_scientific_result(job)
    except (InvalidTransition, ArtifactError, CanonicalizationError):
        return api_error("RESULT_INTEGRITY", "Result artifact verification failed.", 409)
    return JsonResponse({"api_version": API_VERSION, "data": payload, "ok": True})
