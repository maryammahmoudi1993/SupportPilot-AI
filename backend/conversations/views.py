"""Conversation and message views.

Thin by design: resolve tenant-scoped objects via selectors, check a
capability-based permission, and delegate every mutation to
``conversations.services``.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from common.query_params import parse_uuid_filter
from customers.selectors import customer_get_for_workspace_or_404
from workspaces.permissions import IsWorkspaceMember
from workspaces.selectors import get_workspace_member_or_404
from workspaces.views import WorkspaceScopedMixin

from . import selectors, services
from .models import Conversation, Message
from .permissions import CanMutateConversations
from .serializers import (
    ConversationAssignSerializer,
    ConversationCreateSerializer,
    ConversationSerializer,
    ConversationStatusSerializer,
    MessageCreateSerializer,
    MessageSerializer,
)


def _request_id(request) -> str | None:
    return getattr(request, "request_id", None)


def _as_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes"}


class ConversationListCreateView(WorkspaceScopedMixin, generics.ListCreateAPIView):
    """GET: any active member. POST: any non-viewer role."""

    queryset = Conversation.objects.none()

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsWorkspaceMember(), CanMutateConversations()]
        return [IsWorkspaceMember()]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return ConversationCreateSerializer
        return ConversationSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Conversation.objects.none()
        params = self.request.query_params
        return selectors.conversation_list_for_workspace(
            workspace=self.workspace,
            customer_id=parse_uuid_filter(params.get("customer"), param="customer"),
            status=params.get("status"),
            channel=params.get("channel"),
            assigned_to=parse_uuid_filter(params.get("assigned_to"), param="assigned_to"),
            unassigned=_as_bool(params.get("unassigned")),
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        customer = customer_get_for_workspace_or_404(
            workspace=self.workspace, customer_id=data["customer_id"]
        )
        conversation = services.create_conversation(
            workspace=self.workspace,
            customer=customer,
            channel=data["channel"],
            subject=data.get("subject", ""),
            external_id=data.get("external_id"),
            metadata=data.get("metadata"),
        )
        return Response(ConversationSerializer(conversation).data, status=status.HTTP_201_CREATED)


class ConversationDetailView(WorkspaceScopedMixin, APIView):
    """GET: any active member. Field mutation happens only through the
    dedicated action endpoints below — there is deliberately no PATCH here."""

    permission_classes = [IsWorkspaceMember]

    @extend_schema(responses=ConversationSerializer)
    def get(self, request, workspace_id, conversation_id):
        conversation = selectors.conversation_get_for_workspace_or_404(
            workspace=self.workspace, conversation_id=conversation_id
        )
        return Response(ConversationSerializer(conversation).data)


class ConversationAssignView(WorkspaceScopedMixin, APIView):
    """POST: assign/reassign. Managers may target any member; a support
    agent may only self-assign an unassigned conversation."""

    def get_permissions(self):
        return [IsWorkspaceMember(), CanMutateConversations()]

    @extend_schema(request=ConversationAssignSerializer, responses=ConversationSerializer)
    def post(self, request, workspace_id, conversation_id):
        conversation = selectors.conversation_get_for_workspace_or_404(
            workspace=self.workspace, conversation_id=conversation_id
        )
        serializer = ConversationAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership_id = serializer.validated_data.get("membership_id")
        if membership_id is not None:
            target = get_workspace_member_or_404(
                workspace=self.workspace, membership_id=membership_id
            )
        else:
            target = self.membership

        conversation = services.assign_conversation(
            workspace=self.workspace,
            actor=request.user,
            actor_membership=self.membership,
            conversation=conversation,
            target_membership=target,
            request_id=_request_id(request),
        )
        return Response(ConversationSerializer(conversation).data)


class ConversationStatusView(WorkspaceScopedMixin, APIView):
    """POST: generic status transition (e.g. open <-> pending)."""

    def get_permissions(self):
        return [IsWorkspaceMember(), CanMutateConversations()]

    @extend_schema(request=ConversationStatusSerializer, responses=ConversationSerializer)
    def post(self, request, workspace_id, conversation_id):
        conversation = selectors.conversation_get_for_workspace_or_404(
            workspace=self.workspace, conversation_id=conversation_id
        )
        serializer = ConversationStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation = services.change_conversation_status(
            workspace=self.workspace,
            actor=request.user,
            actor_membership=self.membership,
            conversation=conversation,
            new_status=serializer.validated_data["status"],
            request_id=_request_id(request),
        )
        return Response(ConversationSerializer(conversation).data)


class ConversationCloseView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanMutateConversations()]

    @extend_schema(request=None, responses=ConversationSerializer)
    def post(self, request, workspace_id, conversation_id):
        conversation = selectors.conversation_get_for_workspace_or_404(
            workspace=self.workspace, conversation_id=conversation_id
        )
        conversation = services.close_conversation(
            workspace=self.workspace,
            actor=request.user,
            actor_membership=self.membership,
            conversation=conversation,
            request_id=_request_id(request),
        )
        return Response(ConversationSerializer(conversation).data)


class ConversationReopenView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanMutateConversations()]

    @extend_schema(request=None, responses=ConversationSerializer)
    def post(self, request, workspace_id, conversation_id):
        conversation = selectors.conversation_get_for_workspace_or_404(
            workspace=self.workspace, conversation_id=conversation_id
        )
        conversation = services.reopen_conversation(
            workspace=self.workspace,
            actor=request.user,
            actor_membership=self.membership,
            conversation=conversation,
            request_id=_request_id(request),
        )
        return Response(ConversationSerializer(conversation).data)


class MessageListCreateView(WorkspaceScopedMixin, generics.ListCreateAPIView):
    """GET: any active member. POST: any non-viewer role — sender identity
    is always the authenticated staff member, never client-supplied."""

    serializer_class = MessageSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsWorkspaceMember(), CanMutateConversations()]
        return [IsWorkspaceMember()]

    def _conversation(self):
        return selectors.conversation_get_for_workspace_or_404(
            workspace=self.workspace, conversation_id=self.kwargs["conversation_id"]
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Message.objects.none()
        return selectors.message_list_for_conversation(conversation=self._conversation())

    def create(self, request, *args, **kwargs):
        conversation = self._conversation()
        serializer = MessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if data["direction"] == "outbound":
            message = services.create_outbound_message(
                workspace=self.workspace,
                actor_membership=self.membership,
                conversation=conversation,
                body=data["body"],
                external_id=data.get("external_id"),
                metadata=data.get("metadata"),
            )
        else:
            message = services.create_internal_message(
                workspace=self.workspace,
                actor_membership=self.membership,
                conversation=conversation,
                body=data["body"],
                external_id=data.get("external_id"),
                metadata=data.get("metadata"),
            )
        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)
