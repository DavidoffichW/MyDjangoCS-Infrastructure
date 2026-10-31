from __future__ import annotations

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.vary import vary_on_headers

from reliability_lab.middleware import mark_trace

from .forms import AdmissionForm, StepForm, WorkflowForm
from .models import Job, Workflow, WorkflowStep
from .services import (
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
    job = get_object_or_404(Job.objects.select_related("workflow"), pk=job_id)
    return render(request, "workflows/job_detail.html", {"job": job})


@require_POST
def job_execute(request: HttpRequest, job_id) -> HttpResponse:
    mark_trace(request, "view.job_execute")
    try:
        job = execute_job(job_id)
    except InvalidTransition as exc:
        job = get_object_or_404(Job, pk=job_id)
        return render(
            request,
            "workflows/partials/job_panel.html",
            {"job": job, "action_error": str(exc)},
            status=409,
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
    key = f"result:{job.result_digest}:{variant}"
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
