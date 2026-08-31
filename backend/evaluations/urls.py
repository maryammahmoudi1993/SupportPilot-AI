"""Evaluation URLs included below a workspace tenant boundary."""

from django.urls import path

from . import views

app_name = "evaluations"

urlpatterns = [
    path("datasets/", views.EvaluationDatasetListCreateView.as_view(), name="dataset-list"),
    path(
        "datasets/<uuid:dataset_id>/",
        views.EvaluationDatasetDetailView.as_view(),
        name="dataset-detail",
    ),
    path(
        "datasets/<uuid:dataset_id>/cases/",
        views.EvaluationCaseListCreateView.as_view(),
        name="case-list",
    ),
    path(
        "datasets/<uuid:dataset_id>/cases/<uuid:case_id>/",
        views.EvaluationCaseDetailView.as_view(),
        name="case-detail",
    ),
    path("runs/", views.EvaluationRunListCreateView.as_view(), name="run-list"),
    path("runs/<uuid:run_id>/", views.EvaluationRunDetailView.as_view(), name="run-detail"),
    path("runs/<uuid:run_id>/cancel/", views.EvaluationRunCancelView.as_view(), name="run-cancel"),
    path(
        "runs/<uuid:run_id>/results/",
        views.EvaluationResultListView.as_view(),
        name="result-list",
    ),
    path(
        "runs/<uuid:run_id>/results/<uuid:result_id>/",
        views.EvaluationResultDetailView.as_view(),
        name="result-detail",
    ),
    path(
        "runs/<uuid:run_id>/results/<uuid:result_id>/replay/",
        views.EvaluationResultReplayView.as_view(),
        name="result-replay",
    ),
    path("compare/", views.EvaluationRunCompareView.as_view(), name="run-compare"),
]
