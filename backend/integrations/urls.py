"""Integration connection management URLs included below a workspace
tenant boundary (section 64)."""

from django.urls import path

from . import views

app_name = "integrations"

urlpatterns = [
    path("", views.IntegrationConnectionListCreateView.as_view(), name="connection-list"),
    path(
        "<uuid:connection_id>/",
        views.IntegrationConnectionDetailView.as_view(),
        name="connection-detail",
    ),
    path(
        "<uuid:connection_id>/credentials/",
        views.IntegrationConnectionCredentialsView.as_view(),
        name="connection-credentials",
    ),
    path(
        "<uuid:connection_id>/enabled/",
        views.IntegrationConnectionEnabledView.as_view(),
        name="connection-enabled",
    ),
    path(
        "<uuid:connection_id>/test/",
        views.IntegrationConnectionTestView.as_view(),
        name="connection-test",
    ),
]
