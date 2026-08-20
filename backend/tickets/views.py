"""Ticket views.

Thin by design: resolve tenant-scoped objects via selectors, check a
capability-based permission, and delegate every mutation to
``tickets.services``.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from conversations.selectors import conversation_get_for_workspace_or_404
from customers.selectors import customer_get_for_workspace_or_404
from workspaces.permissions import IsWorkspaceMember
from workspaces.selectors import get_workspace_member_or_404
from workspaces.views import WorkspaceScopedMixin

from . import selectors, services
from .models import HumanHandoff, Ticket
from .permissions import CanManageHandoffs, CanMutateTickets
from .serializers import (
    HumanHandoffAssignSerializer,
    HumanHandoffSerializer,
    TicketAssignSerializer,
    TicketCreateSerializer,
    TicketSerializer,
    TicketStatusSerializer,
    TicketUpdateSerializer,
)


def _request_id(request) -> str | None:
    return getattr(request, "request_id", None)


def _as_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes"}


class TicketListCreateView(WorkspaceScopedMixin, generics.ListCreateAPIView):
    """GET: any active member. POST: any non-viewer role."""

    queryset = Ticket.objects.none()

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsWorkspaceMember(), CanMutateTickets()]
        return [IsWorkspaceMember()]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return TicketCreateSerializer
        return TicketSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Ticket.objects.none()
        params = self.request.query_params
        return selectors.ticket_list_for_workspace(
            workspace=self.workspace,
            status=params.get("status"),
            priority=params.get("priority"),
            customer_id=params.get("customer"),
            assigned_to=params.get("assigned_to"),
            unassigned=_as_bool(params.get("unassigned")),
            conversation_id=params.get("conversation"),
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        customer = customer_get_for_workspace_or_404(
            workspace=self.workspace, customer_id=data["customer_id"]
        )
        conversation = None
        if data.get("conversation_id"):
            conversation = conversation_get_for_workspace_or_404(
                workspace=self.workspace, conversation_id=data["conversation_id"]
            )
        ticket = services.create_ticket(
            workspace=self.workspace,
            customer=customer,
            conversation=conversation,
            subject=data["subject"],
            description=data.get("description", ""),
            priority=data.get("priority"),
            due_at=data.get("due_at"),
            metadata=data.get("metadata"),
        )
        return Response(TicketSerializer(ticket).data, status=status.HTTP_201_CREATED)


class TicketDetailView(WorkspaceScopedMixin, APIView):
    """GET: any active member. PATCH: any non-viewer role, restricted at the
    service layer to tickets assigned to the caller unless manager+."""

    def get_permissions(self):
        if self.request.method in {"PATCH", "PUT"}:
            return [IsWorkspaceMember(), CanMutateTickets()]
        return [IsWorkspaceMember()]

    @extend_schema(responses=TicketSerializer)
    def get(self, request, workspace_id, ticket_id):
        ticket = selectors.ticket_get_for_workspace_or_404(
            workspace=self.workspace, ticket_id=ticket_id
        )
        return Response(TicketSerializer(ticket).data)

    @extend_schema(request=TicketUpdateSerializer, responses=TicketSerializer)
    def patch(self, request, workspace_id, ticket_id):
        ticket = selectors.ticket_get_for_workspace_or_404(
            workspace=self.workspace, ticket_id=ticket_id
        )
        serializer = TicketUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        ticket = services.update_ticket(
            workspace=self.workspace,
            ticket=ticket,
            actor_membership=self.membership,
            data=serializer.validated_data,
        )
        return Response(TicketSerializer(ticket).data)


class TicketAssignView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanMutateTickets()]

    @extend_schema(request=TicketAssignSerializer, responses=TicketSerializer)
    def post(self, request, workspace_id, ticket_id):
        ticket = selectors.ticket_get_for_workspace_or_404(
            workspace=self.workspace, ticket_id=ticket_id
        )
        serializer = TicketAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership_id = serializer.validated_data.get("membership_id")
        target = (
            get_workspace_member_or_404(workspace=self.workspace, membership_id=membership_id)
            if membership_id is not None
            else self.membership
        )
        ticket = services.assign_ticket(
            workspace=self.workspace,
            actor=request.user,
            actor_membership=self.membership,
            ticket=ticket,
            target_membership=target,
            request_id=_request_id(request),
        )
        return Response(TicketSerializer(ticket).data)


class TicketUnassignView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanMutateTickets()]

    @extend_schema(request=None, responses=TicketSerializer)
    def post(self, request, workspace_id, ticket_id):
        ticket = selectors.ticket_get_for_workspace_or_404(
            workspace=self.workspace, ticket_id=ticket_id
        )
        ticket = services.unassign_ticket(
            workspace=self.workspace,
            actor=request.user,
            actor_membership=self.membership,
            ticket=ticket,
            request_id=_request_id(request),
        )
        return Response(TicketSerializer(ticket).data)


class TicketStatusView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanMutateTickets()]

    @extend_schema(request=TicketStatusSerializer, responses=TicketSerializer)
    def post(self, request, workspace_id, ticket_id):
        ticket = selectors.ticket_get_for_workspace_or_404(
            workspace=self.workspace, ticket_id=ticket_id
        )
        serializer = TicketStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = services.change_ticket_status(
            workspace=self.workspace,
            actor=request.user,
            actor_membership=self.membership,
            ticket=ticket,
            new_status=serializer.validated_data["status"],
            request_id=_request_id(request),
        )
        return Response(TicketSerializer(ticket).data)


class TicketResolveView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanMutateTickets()]

    @extend_schema(request=None, responses=TicketSerializer)
    def post(self, request, workspace_id, ticket_id):
        ticket = selectors.ticket_get_for_workspace_or_404(
            workspace=self.workspace, ticket_id=ticket_id
        )
        ticket = services.resolve_ticket(
            workspace=self.workspace,
            actor=request.user,
            actor_membership=self.membership,
            ticket=ticket,
            request_id=_request_id(request),
        )
        return Response(TicketSerializer(ticket).data)


class TicketReopenView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanMutateTickets()]

    @extend_schema(request=None, responses=TicketSerializer)
    def post(self, request, workspace_id, ticket_id):
        ticket = selectors.ticket_get_for_workspace_or_404(
            workspace=self.workspace, ticket_id=ticket_id
        )
        ticket = services.reopen_ticket(
            workspace=self.workspace,
            actor=request.user,
            actor_membership=self.membership,
            ticket=ticket,
            request_id=_request_id(request),
        )
        return Response(TicketSerializer(ticket).data)


# ---------------------------------------------------------------------------
# Human handoff (Phase 9, section 53)
# ---------------------------------------------------------------------------


class HumanHandoffListView(WorkspaceScopedMixin, generics.ListAPIView):
    """GET only: no direct-create endpoint. Handoffs are always created by
    orchestration (``agents.orchestration``), never by a raw client POST."""

    queryset = HumanHandoff.objects.none()
    serializer_class = HumanHandoffSerializer

    def get_permissions(self):
        return [IsWorkspaceMember()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return HumanHandoff.objects.none()
        params = self.request.query_params
        return selectors.handoff_list_for_workspace(
            workspace=self.workspace,
            status=params.get("status"),
            conversation_id=params.get("conversation"),
        )


class HumanHandoffDetailView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember()]

    @extend_schema(responses=HumanHandoffSerializer)
    def get(self, request, workspace_id, handoff_id):
        handoff = selectors.handoff_get_for_workspace_or_404(
            workspace=self.workspace, handoff_id=handoff_id
        )
        return Response(HumanHandoffSerializer(handoff).data)


class HumanHandoffAssignView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanManageHandoffs()]

    @extend_schema(request=HumanHandoffAssignSerializer, responses=HumanHandoffSerializer)
    def post(self, request, workspace_id, handoff_id):
        handoff = selectors.handoff_get_for_workspace_or_404(
            workspace=self.workspace, handoff_id=handoff_id
        )
        serializer = HumanHandoffAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership_id = serializer.validated_data.get("membership_id")
        target = (
            get_workspace_member_or_404(workspace=self.workspace, membership_id=membership_id)
            if membership_id is not None
            else self.membership
        )
        handoff = services.assign_handoff(
            workspace=self.workspace,
            actor=request.user,
            actor_membership=self.membership,
            handoff=handoff,
            target_membership=target,
            request_id=_request_id(request),
        )
        return Response(HumanHandoffSerializer(handoff).data)


class HumanHandoffResolveView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanManageHandoffs()]

    @extend_schema(request=None, responses=HumanHandoffSerializer)
    def post(self, request, workspace_id, handoff_id):
        handoff = selectors.handoff_get_for_workspace_or_404(
            workspace=self.workspace, handoff_id=handoff_id
        )
        handoff = services.resolve_handoff(
            workspace=self.workspace,
            actor=request.user,
            actor_membership=self.membership,
            handoff=handoff,
            request_id=_request_id(request),
        )
        return Response(HumanHandoffSerializer(handoff).data)
