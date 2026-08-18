"""Customer URLs. Included under ``workspaces/<workspace_id>/customers/``."""

from django.urls import path

from . import views

app_name = "customers"

urlpatterns = [
    path("", views.CustomerListCreateView.as_view(), name="customer-list"),
    path(
        "<uuid:customer_id>/",
        views.CustomerDetailView.as_view(),
        name="customer-detail",
    ),
]
