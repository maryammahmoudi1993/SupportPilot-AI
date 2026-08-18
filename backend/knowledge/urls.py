"""Knowledge URLs included below a workspace tenant boundary."""

from django.urls import path

from . import views

app_name = "knowledge"

urlpatterns = [
    path("sources/", views.KnowledgeSourceListCreateView.as_view(), name="source-list"),
    path(
        "sources/<uuid:source_id>/",
        views.KnowledgeSourceDetailView.as_view(),
        name="source-detail",
    ),
    path("documents/", views.KnowledgeDocumentListCreateView.as_view(), name="document-list"),
    path(
        "documents/<uuid:document_id>/",
        views.KnowledgeDocumentDetailView.as_view(),
        name="document-detail",
    ),
    path(
        "documents/<uuid:document_id>/retry/",
        views.KnowledgeDocumentRetryView.as_view(),
        name="document-retry",
    ),
    path(
        "ingestion-jobs/<uuid:job_id>/",
        views.KnowledgeIngestionJobDetailView.as_view(),
        name="ingestion-job-detail",
    ),
    path("search/", views.KnowledgeSearchView.as_view(), name="search"),
    path(
        "retrieval-events/<uuid:event_id>/",
        views.RetrievalEventDetailView.as_view(),
        name="retrieval-event-detail",
    ),
]
