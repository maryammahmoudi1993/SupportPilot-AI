"""
URL configuration for SupportPilot AI backend.
"""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from tools.urls import tool_binding_urlpatterns

urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),
    # Health checks
    path("", include("health.urls")),
    # Observability infrastructure (Phase 11 Block 1) — bearer-token
    # protected, outside the versioned product API (see observability/urls.py).
    path("", include("observability.urls")),
    # API v1
    path(
        "api/v1/",
        include(
            [
                # Schema
                path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
                path(
                    "schema/swagger/",
                    SpectacularSwaggerView.as_view(url_name="api-schema"),
                    name="api-docs",
                ),
                # Apps implemented so far. Domain apps without routes yet
                # (notifications) are wired in their own phases.
                path("auth/", include("accounts.urls")),
                path("workspaces/", include("workspaces.urls")),
                path(
                    "workspaces/<uuid:workspace_id>/customers/",
                    include("customers.urls"),
                ),
                path(
                    "workspaces/<uuid:workspace_id>/conversations/",
                    include("conversations.urls"),
                ),
                path(
                    "workspaces/<uuid:workspace_id>/tickets/",
                    include("tickets.urls"),
                ),
                path(
                    "workspaces/<uuid:workspace_id>/knowledge/",
                    include("knowledge.urls"),
                ),
                path(
                    "workspaces/<uuid:workspace_id>/agents/",
                    include("agents.urls"),
                ),
                path(
                    "workspaces/<uuid:workspace_id>/agents/",
                    include((tool_binding_urlpatterns, "tools"), namespace="tool-bindings"),
                ),
                path(
                    "workspaces/<uuid:workspace_id>/agent-runs/",
                    include("agents.run_urls"),
                ),
                path(
                    "workspaces/<uuid:workspace_id>/tools/",
                    include("tools.urls"),
                ),
                path(
                    "workspaces/<uuid:workspace_id>/integrations/",
                    include("integrations.urls"),
                ),
                path(
                    "workspaces/<uuid:workspace_id>/policies/",
                    include("policies.urls"),
                ),
                path(
                    "workspaces/<uuid:workspace_id>/approvals/",
                    include("approvals.urls"),
                ),
                path(
                    "workspaces/<uuid:workspace_id>/handoffs/",
                    include("tickets.handoff_urls"),
                ),
                path(
                    "workspaces/<uuid:workspace_id>/webhooks/",
                    include("webhooks.urls"),
                ),
                path(
                    "workspaces/<uuid:workspace_id>/evaluations/",
                    include("evaluations.urls"),
                ),
                path(
                    "workspaces/<uuid:workspace_id>/channels/",
                    include("channel_ingress.urls"),
                ),
                # Public, unauthenticated multi-channel ingress (Phase 13,
                # section 15, 17, 45) — deliberately NOT nested under
                # workspaces/<uuid:workspace_id>/: every path parameter here
                # is a public routing identifier or session capability, never
                # a client-suppliable workspace id.
                path("channels/public/", include("channel_ingress.public_urls")),
            ]
        ),
    ),
]

# Admin site customization
admin.site.site_header = "SupportPilot AI Admin"
admin.site.site_title = "SupportPilot AI"
