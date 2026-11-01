from django.urls import path

from web_infra.api import v1 as api_views
from web_infra.views import jobs as job_views
from web_infra.views import scientific as scientific_views
from web_infra.views import workflows as workflow_views

urlpatterns = [
    path("", workflow_views.home, name="home"),
    path("lab/", scientific_views.lab_home, name="lab-home"),
    path("lab/seed/", scientific_views.lab_seed, name="lab-seed"),
    path("lab/runs/<uuid:run_id>/", scientific_views.lab_run, name="lab-run"),
    path("lab/runs/<uuid:run_id>/admit/", scientific_views.lab_admit, name="lab-admit"),
    path("api/v1/runs/<uuid:run_id>/state/", api_views.api_state, name="api-state"),
    path("api/v1/runs/<uuid:run_id>/admit/", api_views.api_admit, name="api-admit"),
    path("api/v1/jobs/<uuid:job_id>/result/", api_views.api_job_result, name="api-job-result"),
    path("workflows/", workflow_views.create_workflow, name="workflow-create"),
    path("workflows/<uuid:workflow_id>/", workflow_views.workflow_detail, name="workflow-detail"),
    path("workflows/<uuid:workflow_id>/steps/new/", workflow_views.step_new, name="step-new"),
    path("steps/<uuid:step_id>/edit/", workflow_views.step_edit, name="step-edit"),
    path("steps/<uuid:step_id>/delete/", workflow_views.step_delete, name="step-delete"),
    path("steps/<uuid:step_id>/move/<str:direction>/", workflow_views.step_move, name="step-move"),
    path(
        "workflows/<uuid:workflow_id>/validate/",
        workflow_views.workflow_validate,
        name="workflow-validate",
    ),
    path(
        "workflows/<uuid:workflow_id>/admit/", workflow_views.workflow_admit, name="workflow-admit"
    ),
    path("jobs/<uuid:job_id>/", job_views.job_detail, name="job-detail"),
    path("jobs/<uuid:job_id>/execute/", job_views.job_execute, name="job-execute"),
    path(
        "jobs/<uuid:job_id>/execute-scientific/",
        job_views.scientific_job_execute,
        name="scientific-job-execute",
    ),
    path("jobs/<uuid:job_id>/retry/", job_views.job_retry, name="job-retry"),
    path("jobs/<uuid:job_id>/result/", job_views.job_result, name="job-result"),
]
