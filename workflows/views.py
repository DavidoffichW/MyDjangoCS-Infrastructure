from __future__ import annotations

from django.core.cache import cache
from django.db import OperationalError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.vary import vary_on_headers

from deterministic_lab.canonical import CanonicalizationError, parse_json_strict
from deterministic_lab.errors import AdmissionError, ArtifactError, FoundationError
from reliability_lab.middleware import mark_trace

from .forms import AdmissionForm, ScientificInvestigationForm, StepForm, WorkflowForm
from .models import Job, ResearchRun, Workflow, WorkflowStep
from .scientific_services import (
    admit_investigation,
    execute_scientific_job,
    load_state_by_identity,
    result_cache_identity,
    seed_reference_run,
    verify_scientific_result,
)
from .services import (
    DatabaseBusy,
    IdempotencyConflict,
    InvalidTransition,
    WorkflowValidationError,
    add_step,
    admit_job,
    execute_job,
    move_step,
    remove_step,
    requeue_job,
    update_step,
    validate_workflow,
)


def _step_editor_context(workflow: Workflow, form: StepForm | None = None) -> dict:
    active_form = form or StepForm()
    editing_step = None if active_form.instance._state.adding else active_form.instance
    return {
        "editing_step": editing_step,
        "step_form": active_form,
        "steps": workflow.steps.all(),
        "workflow": workflow,
    }


def _step_response(request: HttpRequest, workflow: Workflow, form: StepForm | None = None):
    context = _step_editor_context(workflow, form)
    if request.htmx:
        return render(request, "workflows/partials/step_editor.html", context)
    return render(request, "workflows/step_page.html", context)


@require_GET
def home(request: HttpRequest) -> HttpResponse:
    mark_trace(request, "view.home")
    return render(
        request,
        "workflows/home.html",
        {"form": WorkflowForm(), "workflows": Workflow.objects.all()[:20]},
    )


@require_GET
def lab_home(request: HttpRequest) -> HttpResponse:
    mark_trace(request, "view.lab_home")
    return render(request, "workflows/lab_home.html", {"runs": ResearchRun.objects.all()})


@require_POST
def lab_seed(request: HttpRequest) -> HttpResponse:
    mark_trace(request, "view.lab_seed")
    run, _ = seed_reference_run()
    return redirect("lab-run", run_id=run.id)


@require_GET
def lab_run(request: HttpRequest, run_id) -> HttpResponse:
    mark_trace(request, "view.lab_run")
    research_run = get_object_or_404(ResearchRun, pk=run_id)
    try:
        state = load_state_by_identity(research_run.state_identity)
    except (KeyError, ArtifactError, FoundationError) as exc:
        return render(
            request,
            "workflows/lab_run.html",
            {"research_run": research_run, "state_error": str(exc)},
            status=409,
        )
    return render(
        request,
        "workflows/lab_run.html",
        {
            "form": ScientificInvestigationForm(),
            "research_run": research_run,
            "state": state,
        },
    )


@require_POST
def lab_admit(request: HttpRequest, run_id) -> HttpResponse:
    mark_trace(request, "view.lab_admit")
    research_run = get_object_or_404(ResearchRun, pk=run_id)
    form = ScientificInvestigationForm(request.POST)
    if form.is_valid():
        try:
            result = admit_investigation(
                research_run,
                form.declaration(research_run),
                form.cleaned_data["idempotency_key"],
            )
        except AdmissionError as exc:
            form.add_error(None, f"{exc.stage}/{exc.code}: {exc}")
        except IdempotencyConflict as exc:
            form.add_error("idempotency_key", str(exc))
        else:
            if request.htmx:
                return render(
                    request,
                    "workflows/partials/lab_admission.html",
                    {"admitted_job": result.job, "research_run": research_run},
                )
            return redirect("job-detail", job_id=result.job.id)
    state = load_state_by_identity(research_run.state_identity)
    if request.htmx:
        return render(
            request,
            "workflows/partials/lab_admission.html",
            {"form": form, "research_run": research_run},
            status=400,
        )
    return render(
        request,
        "workflows/lab_run.html",
        {"form": form, "research_run": research_run, "state": state},
        status=400,
    )


@require_POST
def create_workflow(request: HttpRequest) -> HttpResponse:
    mark_trace(request, "view.create_workflow")
    form = WorkflowForm(request.POST)
    if form.is_valid():
        return redirect("workflow-detail", workflow_id=form.save().id)
    return render(
        request,
        "workflows/home.html",
        {"form": form, "workflows": Workflow.objects.all()[:20]},
        status=400,
    )


@require_GET
def workflow_detail(request: HttpRequest, workflow_id) -> HttpResponse:
    mark_trace(request, "view.workflow_detail")
    workflow = get_object_or_404(Workflow, pk=workflow_id)
    return render(
        request,
        "workflows/workflow_detail.html",
        {
            **_step_editor_context(workflow),
            "admission_form": AdmissionForm(),
            "jobs": workflow.jobs.all().order_by("-created_at")[:10],
        },
    )


def step_new(request: HttpRequest, workflow_id) -> HttpResponse:
    mark_trace(request, "view.step_new")
    workflow = get_object_or_404(Workflow, pk=workflow_id)
    form = StepForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            add_step(
                workflow,
                operation=form.cleaned_data["operation"],
                parameter=form.cleaned_data["parameter"],
            )
        except WorkflowValidationError as exc:
            form.add_error(None, str(exc))
        else:
            form = StepForm()
    return _step_response(request, workflow, form)


def step_edit(request: HttpRequest, step_id) -> HttpResponse:
    mark_trace(request, "view.step_edit")
    step = get_object_or_404(WorkflowStep.objects.select_related("workflow"), pk=step_id)
    form = StepForm(request.POST or None, instance=step)
    if request.method == "POST" and form.is_valid():
        update_step(
            step,
            operation=form.cleaned_data["operation"],
            parameter=form.cleaned_data["parameter"],
        )
        form = StepForm()
    return _step_response(request, step.workflow, form)


@require_POST
def step_delete(request: HttpRequest, step_id) -> HttpResponse:
    mark_trace(request, "view.step_delete")
    step = get_object_or_404(WorkflowStep.objects.select_related("workflow"), pk=step_id)
    workflow = step.workflow
    remove_step(step)
    return _step_response(request, workflow)


@require_POST
def step_move(request: HttpRequest, step_id, direction: str) -> HttpResponse:
    mark_trace(request, "view.step_move")
    step = get_object_or_404(WorkflowStep.objects.select_related("workflow"), pk=step_id)
    move_step(step, direction)
    return _step_response(request, step.workflow)


@require_POST
def workflow_validate(request: HttpRequest, workflow_id) -> HttpResponse:
    mark_trace(request, "view.workflow_validate")
    workflow = get_object_or_404(Workflow, pk=workflow_id)
    form = AdmissionForm(request.POST)
    if form.is_valid():
        try:
            validated = validate_workflow(workflow, form.cleaned_data["input_values"])
        except WorkflowValidationError as exc:
            form.add_error(None, str(exc))
        else:
            return render(
                request,
                "workflows/partials/validation_result.html",
                {
                    "digest": validated["input_digest"],
                    "step_count": len(validated["snapshot"]["steps"]),
                },
            )
    return render(
        request,
        "workflows/partials/admission_form.html",
        {"form": form, "workflow": workflow},
        status=400,
    )


@require_POST
def workflow_admit(request: HttpRequest, workflow_id) -> HttpResponse:
    mark_trace(request, "view.workflow_admit")
    workflow = get_object_or_404(Workflow, pk=workflow_id)
    form = AdmissionForm(request.POST)
    if form.is_valid():
        try:
            result = admit_job(
                workflow,
                form.cleaned_data["input_values"],
                form.cleaned_data["idempotency_key"],
            )
        except (WorkflowValidationError, IdempotencyConflict) as exc:
            form.add_error(None, str(exc))
        else:
            if request.htmx:
                return render(
                    request,
                    "workflows/partials/admission_result.html",
                    {"job": result.job, "duplicate": result.duplicate},
                )
            return redirect("job-detail", job_id=result.job.id)
    return render(
        request,
        "workflows/partials/admission_form.html",
        {"form": form, "workflow": workflow},
        status=409 if form.non_field_errors() else 400,
    )


@never_cache
@require_GET
def job_detail(request: HttpRequest, job_id) -> HttpResponse:
    mark_trace(request, "view.job_detail")
    job = get_object_or_404(
        Job.objects.select_related("workflow", "admission__investigation__research_run"),
        pk=job_id,
    )
    return render(request, "workflows/job_detail.html", {"job": job})


@require_POST
def job_execute(request: HttpRequest, job_id) -> HttpResponse:
    mark_trace(request, "view.job_execute")
    try:
        job = execute_job(job_id)
    except (DatabaseBusy, InvalidTransition) as exc:
        try:
            job = Job.objects.get(pk=job_id)
        except OperationalError:
            return HttpResponse(
                "The SQLite state transition is still committing; retry the request.",
                status=503,
            )
        except Job.DoesNotExist:
            return HttpResponse("Job not found.", status=404)
        return render(
            request,
            "workflows/partials/job_panel.html",
            {"job": job, "action_error": str(exc)},
            status=503 if isinstance(exc, DatabaseBusy) else 409,
        )
    return render(request, "workflows/partials/job_panel.html", {"job": job})


@require_POST
def scientific_job_execute(request: HttpRequest, job_id) -> HttpResponse:
    mark_trace(request, "view.scientific_job_execute")
    try:
        job = execute_scientific_job(job_id)
    except (DatabaseBusy, InvalidTransition) as exc:
        job = get_object_or_404(Job, pk=job_id)
        return render(
            request,
            "workflows/partials/job_panel.html",
            {"job": job, "action_error": str(exc)},
            status=503 if isinstance(exc, DatabaseBusy) else 409,
        )
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
    variant = "fragment" if request.htmx else "page"
    if job.admission_id:
        try:
            verify_scientific_result(job)
        except (InvalidTransition, ArtifactError, CanonicalizationError):
            return HttpResponse(
                "The authoritative result artifact failed verification.",
                status=409,
            )
        cache_identity = result_cache_identity(job, variant)
    else:
        cache_identity = f"legacy:{job.id}:{job.result_digest}:{variant}"
    key = f"result:{cache_identity}"
    content = cache.get(key)
    cache_status = "HIT"
    if content is None:
        template = "workflows/partials/result.html" if request.htmx else "workflows/result.html"
        content = render_to_string(template, {"job": job}, request=request)
        cache.set(key, content, timeout=300)
        cache_status = "MISS"
    response = HttpResponse(content)
    response.headers["X-Lab-Cache"] = cache_status
    response.headers["Cache-Control"] = "private, max-age=60"
    return response


def _api_error(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse(
        {
            "api_version": "mydjangocs.http-api/1",
            "error": {"code": code, "message": message},
            "ok": False,
        },
        status=status,
    )


@require_GET
def api_state(request: HttpRequest, run_id) -> JsonResponse:
    research_run = ResearchRun.objects.filter(pk=run_id).first()
    if research_run is None:
        return _api_error("RUN_NOT_FOUND", "Research run was not found.", 404)
    try:
        state = load_state_by_identity(research_run.state_identity)
    except (KeyError, ArtifactError, FoundationError):
        return _api_error("STATE_UNAVAILABLE", "Verified state is unavailable.", 409)
    return JsonResponse(
        {"api_version": "mydjangocs.http-api/1", "data": state.to_dict(), "ok": True}
    )


@require_POST
def api_admit(request: HttpRequest, run_id) -> JsonResponse:
    research_run = ResearchRun.objects.filter(pk=run_id).first()
    if research_run is None:
        return _api_error("RUN_NOT_FOUND", "Research run was not found.", 404)
    try:
        envelope = parse_json_strict(request.body)
        if not isinstance(envelope, dict) or set(envelope) != {
            "declaration",
            "idempotency_key",
        }:
            return _api_error("INVALID_ENVELOPE", "Request envelope fields are invalid.", 400)
        result = admit_investigation(
            research_run,
            envelope["declaration"],
            envelope["idempotency_key"],
        )
    except CanonicalizationError:
        return _api_error("INVALID_JSON", "Request is not valid restricted JSON.", 400)
    except AdmissionError as exc:
        return _api_error(exc.code, str(exc), 422)
    except IdempotencyConflict as exc:
        return _api_error("IDEMPOTENCY_CONFLICT", str(exc), 409)
    return JsonResponse(
        {
            "api_version": "mydjangocs.http-api/1",
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
        return _api_error("JOB_NOT_FOUND", "Job was not found.", 404)
    if not job.admission_id or job.state != Job.State.SUCCEEDED:
        return _api_error("RESULT_UNAVAILABLE", "Verified scientific result is unavailable.", 409)
    try:
        payload = verify_scientific_result(job)
    except (InvalidTransition, ArtifactError, CanonicalizationError):
        return _api_error("RESULT_INTEGRITY", "Result artifact verification failed.", 409)
    return JsonResponse(
        {"api_version": "mydjangocs.http-api/1", "data": payload, "ok": True}
    )
