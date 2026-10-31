from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("workflows/", views.create_workflow, name="workflow-create"),
    path("workflows/<uuid:workflow_id>/", views.workflow_detail, name="workflow-detail"),
    path("workflows/<uuid:workflow_id>/steps/new/", views.step_new, name="step-new"),
    path("steps/<uuid:step_id>/edit/", views.step_edit, name="step-edit"),
    path("steps/<uuid:step_id>/delete/", views.step_delete, name="step-delete"),
    path("steps/<uuid:step_id>/move/<str:direction>/", views.step_move, name="step-move"),
    path(
        "workflows/<uuid:workflow_id>/validate/", views.workflow_validate, name="workflow-validate"
    ),
    path("workflows/<uuid:workflow_id>/admit/", views.workflow_admit, name="workflow-admit"),
    path("jobs/<uuid:job_id>/", views.job_detail, name="job-detail"),
    path("jobs/<uuid:job_id>/execute/", views.job_execute, name="job-execute"),
    path("jobs/<uuid:job_id>/retry/", views.job_retry, name="job-retry"),
    path("jobs/<uuid:job_id>/result/", views.job_result, name="job-result"),
]
