"""Tool catalog, binding, and execution-history URLs included below a
workspace tenant boundary."""

from django.urls import path

from . import views

app_name = "tools"

urlpatterns = [
    path("", views.ToolCatalogListView.as_view(), name="tool-catalog"),
    path(
        "tool-executions/",
        views.ToolExecutionListView.as_view(),
        name="tool-execution-list",
    ),
    path(
        "tool-executions/<uuid:execution_id>/",
        views.ToolExecutionDetailView.as_view(),
        name="tool-execution-detail",
    ),
]


tool_binding_urlpatterns = [
    path(
        "<uuid:agent_id>/versions/<uuid:version_id>/tool-bindings/",
        views.ToolBindingListCreateView.as_view(),
        name="tool-binding-list",
    ),
    path(
        "<uuid:agent_id>/versions/<uuid:version_id>/tool-bindings/<uuid:binding_id>/",
        views.ToolBindingDetailView.as_view(),
        name="tool-binding-detail",
    ),
]
