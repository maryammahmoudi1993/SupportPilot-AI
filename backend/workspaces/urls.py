"""Workspaces URLs."""

from django.urls import path

from . import views

app_name = "workspaces"

urlpatterns = [
    path("", views.WorkspaceListCreateView.as_view(), name="workspace-list"),
    path("<uuid:workspace_id>/", views.WorkspaceDetailView.as_view(), name="workspace-detail"),
    path(
        "<uuid:workspace_id>/members/",
        views.WorkspaceMemberListCreateView.as_view(),
        name="member-list",
    ),
    path(
        "<uuid:workspace_id>/members/<uuid:membership_id>/",
        views.WorkspaceMemberDetailView.as_view(),
        name="member-detail",
    ),
    path(
        "<uuid:workspace_id>/transfer-ownership/",
        views.WorkspaceOwnershipTransferView.as_view(),
        name="transfer-ownership",
    ),
]
