"""Policy management URLs, mounted under
``/api/v1/workspaces/<workspace_id>/policies/``."""

from __future__ import annotations

from django.urls import path

from .views import (
    PolicyActivateView,
    PolicyDeactivateView,
    PolicyDetailView,
    PolicyListCreateView,
    PolicyRuleListCreateView,
    PolicyVersionDetailView,
    PolicyVersionListCreateView,
    PolicyVersionPublishView,
)

app_name = "policies"

urlpatterns = [
    path("", PolicyListCreateView.as_view(), name="policy-list-create"),
    path("<uuid:policy_id>/", PolicyDetailView.as_view(), name="policy-detail"),
    path("<uuid:policy_id>/activate/", PolicyActivateView.as_view(), name="policy-activate"),
    path("<uuid:policy_id>/deactivate/", PolicyDeactivateView.as_view(), name="policy-deactivate"),
    path(
        "<uuid:policy_id>/versions/",
        PolicyVersionListCreateView.as_view(),
        name="policy-version-list-create",
    ),
    path(
        "<uuid:policy_id>/versions/<uuid:version_id>/",
        PolicyVersionDetailView.as_view(),
        name="policy-version-detail",
    ),
    path(
        "<uuid:policy_id>/versions/<uuid:version_id>/publish/",
        PolicyVersionPublishView.as_view(),
        name="policy-version-publish",
    ),
    path(
        "<uuid:policy_id>/versions/<uuid:version_id>/rules/",
        PolicyRuleListCreateView.as_view(),
        name="policy-rule-list-create",
    ),
]
