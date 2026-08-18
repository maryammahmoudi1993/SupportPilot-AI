"""Agent definition/version URLs included below a workspace tenant boundary."""

from django.urls import path

from . import views

app_name = "agents"

urlpatterns = [
    path("", views.AgentDefinitionListCreateView.as_view(), name="agent-list"),
    path("<uuid:agent_id>/", views.AgentDefinitionDetailView.as_view(), name="agent-detail"),
    path(
        "<uuid:agent_id>/versions/",
        views.AgentVersionListCreateView.as_view(),
        name="agent-version-list",
    ),
    path(
        "<uuid:agent_id>/versions/<uuid:version_id>/publish/",
        views.AgentVersionPublishView.as_view(),
        name="agent-version-publish",
    ),
]
