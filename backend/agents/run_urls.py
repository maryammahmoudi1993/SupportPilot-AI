"""Agent-run URLs included below a workspace tenant boundary."""

from django.urls import path

from . import views

app_name = "agent-runs"

urlpatterns = [
    path("", views.AgentRunListCreateView.as_view(), name="agent-run-list"),
    path("<uuid:run_id>/", views.AgentRunDetailView.as_view(), name="agent-run-detail"),
    path("<uuid:run_id>/steps/", views.AgentRunStepsView.as_view(), name="agent-run-steps"),
    path("<uuid:run_id>/cancel/", views.AgentRunCancelView.as_view(), name="agent-run-cancel"),
]
