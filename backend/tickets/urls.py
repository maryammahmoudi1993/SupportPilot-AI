"""Ticket URLs. Included under ``workspaces/<workspace_id>/tickets/``."""

from django.urls import path

from . import views

app_name = "tickets"

urlpatterns = [
    path("", views.TicketListCreateView.as_view(), name="ticket-list"),
    path("<uuid:ticket_id>/", views.TicketDetailView.as_view(), name="ticket-detail"),
    path("<uuid:ticket_id>/assign/", views.TicketAssignView.as_view(), name="ticket-assign"),
    path("<uuid:ticket_id>/unassign/", views.TicketUnassignView.as_view(), name="ticket-unassign"),
    path("<uuid:ticket_id>/status/", views.TicketStatusView.as_view(), name="ticket-status"),
    path("<uuid:ticket_id>/resolve/", views.TicketResolveView.as_view(), name="ticket-resolve"),
    path("<uuid:ticket_id>/reopen/", views.TicketReopenView.as_view(), name="ticket-reopen"),
]
