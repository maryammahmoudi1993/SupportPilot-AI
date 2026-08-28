"""Webhook endpoint/delivery management URLs, included below a workspace
tenant boundary (section 36)."""

from django.urls import path

from . import views

app_name = "webhooks"

urlpatterns = [
    path(
        "endpoints/",
        views.WebhookEndpointListCreateView.as_view(),
        name="endpoint-list",
    ),
    path(
        "endpoints/<uuid:endpoint_id>/",
        views.WebhookEndpointDetailView.as_view(),
        name="endpoint-detail",
    ),
    path(
        "endpoints/<uuid:endpoint_id>/status/",
        views.WebhookEndpointStatusView.as_view(),
        name="endpoint-status",
    ),
    path(
        "endpoints/<uuid:endpoint_id>/rotate-secret/",
        views.WebhookEndpointRotateSecretView.as_view(),
        name="endpoint-rotate-secret",
    ),
    path(
        "deliveries/",
        views.WebhookDeliveryListView.as_view(),
        name="delivery-list",
    ),
    path(
        "deliveries/<uuid:delivery_id>/",
        views.WebhookDeliveryDetailView.as_view(),
        name="delivery-detail",
    ),
    path(
        "deliveries/<uuid:delivery_id>/redrive/",
        views.WebhookDeliveryRedriveView.as_view(),
        name="delivery-redrive",
    ),
]
