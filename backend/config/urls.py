"""
URL configuration for SupportPilot AI backend.
"""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),
    # Health checks
    path("", include("health.urls")),
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
                # Apps implemented so far. Domain apps without routes yet (knowledge,
                # agents, tools, integrations, policies, approvals, notifications,
                # evaluations, audit, observability) are wired in their own phases.
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
            ]
        ),
    ),
]

# Admin site customization
admin.site.site_header = "SupportPilot AI Admin"
admin.site.site_title = "SupportPilot AI"
