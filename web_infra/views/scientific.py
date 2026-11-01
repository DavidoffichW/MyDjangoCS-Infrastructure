"""Scientific run inspection and investigation admission views."""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from foundation.contracts.errors import AdmissionError, ArtifactError, FoundationError
from services.scientific import admit_investigation, load_state_by_identity, seed_reference_run
from services.workflows import IdempotencyConflict
from web_infra.middleware.tracing import mark_trace
from workflows.forms import ScientificInvestigationForm
from workflows.models import ResearchRun


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
        {"form": ScientificInvestigationForm(), "research_run": research_run, "state": state},
    )


@require_POST
def lab_admit(request: HttpRequest, run_id) -> HttpResponse:
    mark_trace(request, "view.lab_admit")
    research_run = get_object_or_404(ResearchRun, pk=run_id)
    form = ScientificInvestigationForm(request.POST)
    if form.is_valid():
        try:
            result = admit_investigation(
                research_run, form.declaration(research_run), form.cleaned_data["idempotency_key"]
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
