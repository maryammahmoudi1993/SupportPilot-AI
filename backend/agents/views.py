"""Thin workspace-scoped agent configuration and run views."""

from __future__ import annotations

from django.http import Http404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from common.exceptions import ConflictError, SafeAPIError
from conversations.selectors import (
    conversation_get_for_workspace_or_404,
    message_get_for_workspace_or_404,
)
from tickets.selectors import ticket_get_for_workspace_or_404
from workspaces.permissions import IsWorkspaceMember
from workspaces.views import WorkspaceScopedMixin

from . import orchestration, selectors, services
from .errors import AgentError
from .models import AgentDefinition, AgentRun, AgentVersion
from .permissions import CanConfigureAgents, CanRunAgents
from .serializers import (
    AgentDefinitionSerializer,
    AgentDefinitionWriteSerializer,
    AgentRunCreateSerializer,
    AgentRunSerializer,
    AgentStepSerializer,
    AgentVersionSerializer,
    AgentVersionWriteSerializer,
)


def _request_id(request) -> str | None:
    return getattr(request, "request_id", None)


class AgentDefinitionListCreateView(WorkspaceScopedMixin, generics.ListCreateAPIView):
    queryset = AgentDefinition.objects.none()

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsWorkspaceMember(), CanConfigureAgents()]
        return [IsWorkspaceMember()]

    def get_serializer_class(self):
        return (
            AgentDefinitionWriteSerializer
            if self.request.method == "POST"
            else AgentDefinitionSerializer
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AgentDefinition.objects.none()
        return selectors.agent_definition_list_for_workspace(
            workspace=self.workspace, status=self.request.query_params.get("status")
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        definition = services.create_agent_definition(
            workspace=self.workspace,
            actor=request.user,
            data=serializer.validated_data,
            request_id=_request_id(request),
        )
        return Response(AgentDefinitionSerializer(definition).data, status=status.HTTP_201_CREATED)


class AgentDefinitionDetailView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        if self.request.method in {"PATCH", "PUT"}:
            return [IsWorkspaceMember(), CanConfigureAgents()]
        return [IsWorkspaceMember()]

    @extend_schema(responses=AgentDefinitionSerializer)
    def get(self, request, workspace_id, agent_id):
        definition = selectors.agent_definition_get_for_workspace_or_404(
            workspace=self.workspace, agent_id=agent_id
        )
        return Response(AgentDefinitionSerializer(definition).data)

    @extend_schema(request=AgentDefinitionWriteSerializer, responses=AgentDefinitionSerializer)
    def patch(self, request, workspace_id, agent_id):
        definition = selectors.agent_definition_get_for_workspace_or_404(
            workspace=self.workspace, agent_id=agent_id
        )
        serializer = AgentDefinitionWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        definition = services.update_agent_definition(
            workspace=self.workspace,
            definition=definition,
            actor=request.user,
            data=serializer.validated_data,
            request_id=_request_id(request),
        )
        return Response(AgentDefinitionSerializer(definition).data)


class AgentVersionListCreateView(WorkspaceScopedMixin, generics.ListCreateAPIView):
    queryset = AgentDefinition.objects.none()

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsWorkspaceMember(), CanConfigureAgents()]
        return [IsWorkspaceMember()]

    def get_serializer_class(self):
        return (
            AgentVersionWriteSerializer if self.request.method == "POST" else AgentVersionSerializer
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AgentDefinition.objects.none()
        definition = selectors.agent_definition_get_for_workspace_or_404(
            workspace=self.workspace, agent_id=self.kwargs["agent_id"]
        )
        return selectors.agent_version_list_for_definition(
            workspace=self.workspace, agent_definition=definition
        )

    def create(self, request, *args, **kwargs):
        definition = selectors.agent_definition_get_for_workspace_or_404(
            workspace=self.workspace, agent_id=self.kwargs["agent_id"]
        )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        version = services.create_agent_version(
            workspace=self.workspace,
            agent_definition=definition,
            actor=request.user,
            data=serializer.validated_data,
            request_id=_request_id(request),
        )
        return Response(AgentVersionSerializer(version).data, status=status.HTTP_201_CREATED)


class AgentVersionPublishView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanConfigureAgents()]

    @extend_schema(
        request=None,
        responses={200: AgentVersionSerializer, 409: OpenApiResponse(description="Not a draft.")},
    )
    def post(self, request, workspace_id, agent_id, version_id):
        definition = selectors.agent_definition_get_for_workspace_or_404(
            workspace=self.workspace, agent_id=agent_id
        )
        version = selectors.agent_version_get_for_workspace_or_404(
            workspace=self.workspace, agent_definition=definition, version_id=version_id
        )
        try:
            version = services.publish_agent_version(
                workspace=self.workspace,
                version=version,
                actor=request.user,
                request_id=_request_id(request),
            )
        except AgentError as exc:
            raise ConflictError(exc.safe_message) from exc
        return Response(AgentVersionSerializer(version).data)


class AgentRunListCreateView(WorkspaceScopedMixin, generics.ListCreateAPIView):
    queryset = AgentRun.objects.none()

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsWorkspaceMember(), CanRunAgents()]
        return [IsWorkspaceMember()]

    def get_serializer_class(self):
        return AgentRunCreateSerializer if self.request.method == "POST" else AgentRunSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AgentRun.objects.none()
        return selectors.agent_run_list_for_workspace(
            workspace=self.workspace,
            status=self.request.query_params.get("status"),
            agent_definition_id=self.request.query_params.get("agent_id"),
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # agent_version_id is resolved through a workspace-scoped filter so a
        # version belonging to another workspace 404s rather than being
        # resolvable (no existence leakage across tenants).
        version = AgentVersion.objects.filter(
            pk=data["agent_version_id"], agent_definition__workspace=self.workspace
        ).first()
        if version is None:
            raise Http404("Agent version not found.")

        conversation = None
        if data.get("conversation_id"):
            conversation = conversation_get_for_workspace_or_404(
                workspace=self.workspace, conversation_id=data["conversation_id"]
            )
        ticket = None
        if data.get("ticket_id"):
            ticket = ticket_get_for_workspace_or_404(
                workspace=self.workspace, ticket_id=data["ticket_id"]
            )

        try:
            if data.get("trigger_message_id"):
                # Orchestrated path (section 17-19, 97): idempotent per
                # trigger message, routed through agents.orchestration.
                trigger_message = message_get_for_workspace_or_404(
                    workspace=self.workspace,
                    conversation=conversation,
                    message_id=data["trigger_message_id"],
                )
                run = orchestration.start_support_agent_run(
                    workspace=self.workspace,
                    actor=request.user,
                    conversation=conversation,
                    trigger_message=trigger_message,
                    agent_version=version,
                    request_id=_request_id(request),
                )
            else:
                run = services.create_agent_run(
                    workspace=self.workspace,
                    agent_version=version,
                    actor=request.user,
                    input_message=data["input_message"],
                    trigger=data.get("trigger", "manual"),
                    conversation=conversation,
                    ticket=ticket,
                    input_metadata=data.get("input_metadata"),
                    request_id=_request_id(request),
                )
        except AgentError as exc:
            raise SafeAPIError(exc.safe_message, code=exc.code) from exc
        return Response(AgentRunSerializer(run).data, status=status.HTTP_201_CREATED)


class AgentRunDetailView(WorkspaceScopedMixin, APIView):
    @extend_schema(responses=AgentRunSerializer)
    def get(self, request, workspace_id, run_id):
        run = selectors.agent_run_get_for_workspace_or_404(workspace=self.workspace, run_id=run_id)
        return Response(AgentRunSerializer(run).data)


class AgentRunStepsView(WorkspaceScopedMixin, APIView):
    @extend_schema(responses=AgentStepSerializer(many=True))
    def get(self, request, workspace_id, run_id):
        run = selectors.agent_run_get_for_workspace_or_404(workspace=self.workspace, run_id=run_id)
        steps = selectors.agent_step_list_for_run(workspace=self.workspace, run=run)
        return Response(AgentStepSerializer(steps, many=True).data)


class AgentRunCancelView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanRunAgents()]

    @extend_schema(
        request=None,
        responses={200: AgentRunSerializer, 409: OpenApiResponse(description="Not cancellable.")},
    )
    def post(self, request, workspace_id, run_id):
        run = selectors.agent_run_get_for_workspace_or_404(workspace=self.workspace, run_id=run_id)
        try:
            run = orchestration.cancel_support_agent_run(
                workspace=self.workspace,
                run=run,
                actor=request.user,
                request_id=_request_id(request),
            )
        except AgentError as exc:
            raise ConflictError(exc.safe_message) from exc
        return Response(AgentRunSerializer(run).data)
