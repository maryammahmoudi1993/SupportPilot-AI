"""Human handoff URLs. Included under ``workspaces/<workspace_id>/handoffs/``
(section 53 of the Phase 9 brief) — a distinct top-level namespace from
``tickets.urls`` since a handoff is not itself a ticket."""

from django.urls import path

from . import views

app_name = "handoffs"

urlpatterns = [
    path("", views.HumanHandoffListView.as_view(), name="handoff-list"),
    path("<uuid:handoff_id>/", views.HumanHandoffDetailView.as_view(), name="handoff-detail"),
    path(
        "<uuid:handoff_id>/assign/",
        views.HumanHandoffAssignView.as_view(),
        name="handoff-assign",
    ),
    path(
        "<uuid:handoff_id>/resolve/",
        views.HumanHandoffResolveView.as_view(),
        name="handoff-resolve",
    ),
]
