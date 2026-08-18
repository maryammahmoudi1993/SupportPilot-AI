"""Conversation URLs. Included under ``workspaces/<workspace_id>/conversations/``."""

from django.urls import path

from . import views

app_name = "conversations"

urlpatterns = [
    path("", views.ConversationListCreateView.as_view(), name="conversation-list"),
    path(
        "<uuid:conversation_id>/",
        views.ConversationDetailView.as_view(),
        name="conversation-detail",
    ),
    path(
        "<uuid:conversation_id>/assign/",
        views.ConversationAssignView.as_view(),
        name="conversation-assign",
    ),
    path(
        "<uuid:conversation_id>/status/",
        views.ConversationStatusView.as_view(),
        name="conversation-status",
    ),
    path(
        "<uuid:conversation_id>/close/",
        views.ConversationCloseView.as_view(),
        name="conversation-close",
    ),
    path(
        "<uuid:conversation_id>/reopen/",
        views.ConversationReopenView.as_view(),
        name="conversation-reopen",
    ),
    path(
        "<uuid:conversation_id>/messages/",
        views.MessageListCreateView.as_view(),
        name="message-list",
    ),
]
