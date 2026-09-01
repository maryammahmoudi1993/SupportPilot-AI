"""Staff-facing channel endpoint/ingress-event management URLs, included
below the workspace tenant boundary (mirrors ``webhooks.urls``)."""

from django.urls import path

from . import views

app_name = "channel_ingress"

urlpatterns = [
    path("endpoints/", views.ChannelEndpointListCreateView.as_view(), name="endpoint-list"),
    path(
        "endpoints/<uuid:endpoint_id>/",
        views.ChannelEndpointDetailView.as_view(),
        name="endpoint-detail",
    ),
    path(
        "endpoints/<uuid:endpoint_id>/status/",
        views.ChannelEndpointStatusView.as_view(),
        name="endpoint-status",
    ),
    path(
        "endpoints/<uuid:endpoint_id>/rotate-secret/",
        views.ChannelEndpointRotateSecretView.as_view(),
        name="endpoint-rotate-secret",
    ),
    path("events/", views.InboundChannelEventListView.as_view(), name="event-list"),
    path(
        "events/<uuid:event_id>/",
        views.InboundChannelEventDetailView.as_view(),
        name="event-detail",
    ),
]
