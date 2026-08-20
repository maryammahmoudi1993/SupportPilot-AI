"""Approval URLs, mounted under
``/api/v1/workspaces/<workspace_id>/approvals/``."""

from __future__ import annotations

from django.urls import path

from .views import (
    ApprovalApproveView,
    ApprovalRejectView,
    ApprovalRequestDetailView,
    ApprovalRequestListView,
)

app_name = "approvals"

urlpatterns = [
    path("", ApprovalRequestListView.as_view(), name="approval-list"),
    path("<uuid:approval_id>/", ApprovalRequestDetailView.as_view(), name="approval-detail"),
    path("<uuid:approval_id>/approve/", ApprovalApproveView.as_view(), name="approval-approve"),
    path("<uuid:approval_id>/reject/", ApprovalRejectView.as_view(), name="approval-reject"),
]
