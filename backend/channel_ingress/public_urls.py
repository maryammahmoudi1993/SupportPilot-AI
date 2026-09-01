"""Public, unauthenticated ingress URLs (section 15, 17, 45) — deliberately
outside the ``workspaces/<uuid:workspace_id>/...`` staff/RBAC boundary.
Every path parameter here is a public routing identifier
(``ChannelEndpoint.id``) or an opaque session capability
(``session_token``), never a workspace id or anything else a caller could
turn into cross-tenant access."""

from django.urls import path

from . import views

app_name = "channel_ingress_public"

urlpatterns = [
    path(
        "webchat/<uuid:endpoint_id>/session/",
        views.ChatSessionBootstrapView.as_view(),
        name="webchat-session-bootstrap",
    ),
    path(
        "webchat/session/<str:session_token>/messages/",
        views.ChatMessageListCreateView.as_view(),
        name="webchat-session-messages",
    ),
    path(
        "inbound/<uuid:endpoint_id>/",
        views.InboundWebhookView.as_view(),
        name="inbound-webhook",
    ),
]
