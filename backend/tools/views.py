"""Thin workspace-scoped tool catalog, binding, and execution-history views.

Deliberately no direct "execute this tool" endpoint (section 58): runtime
execution only ever happens through the bounded agent runtime.
"""

from __future__ import annotations

from django.http import Http404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from agents.errors import AgentVersionImmutableError
from common.exceptions import ConflictError
from workspaces.permissions import IsWorkspaceMember
from workspaces.views import WorkspaceScopedMixin

from . import selectors, services
from .errors import ToolError
from .models import ToolBinding, ToolDefinition, ToolExecution
from .permissions import CanConfigureTools
from .serializers import (
    ToolBindingCreateSerializer,
    ToolBindingSerializer,
    ToolBindingUpdateSerializer,
    ToolDefinitionSerializer,
    ToolExecutionSerializer,
)


def _request_id(request) -> str | None:
    return getattr(request, "request_id", None)


class ToolCatalogListView(WorkspaceScopedMixin, generics.ListAPIView):
    """The global, code-owned tool catalog — safe metadata only."""

    serializer_class = ToolDefinitionSerializer
    permission_classes = [IsWorkspaceMember]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ToolDefinition.objects.none()
        return selectors.tool_definition_catalog()


class ToolBindingListCreateView(WorkspaceScopedMixin, generics.ListCreateAPIView):
    queryset = ToolBinding.objects.none()

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsWorkspaceMember(), CanConfigureTools()]
        return [IsWorkspaceMember()]

    def get_serializer_class(self):
        return (
            ToolBindingCreateSerializer if self.request.method == "POST" else ToolBindingSerializer
        )

    def _agent_version(self):
        return selectors.agent_version_get_for_workspace_or_404(
            workspace=self.workspace,
            agent_id=self.kwargs["agent_id"],
            version_id=self.kwargs["version_id"],
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ToolBinding.objects.none()
        return selectors.tool_binding_list_for_version(
            workspace=self.workspace, agent_version=self._agent_version()
        )

    def create(self, request, *args, **kwargs):
        agent_version = self._agent_version()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tool_definition = ToolDefinition.objects.filter(
            key=serializer.validated_data["tool_key"]
        ).first()
        if tool_definition is None:
            raise Http404("Tool not found.")
        try:
            binding = services.create_tool_binding(
                workspace=self.workspace,
                agent_version=agent_version,
                actor=request.user,
                tool_definition=tool_definition,
                configuration=serializer.validated_data.get("configuration"),
                request_id=_request_id(request),
            )
        except (ToolError, AgentVersionImmutableError) as exc:
            raise ConflictError(exc.safe_message) from exc
        return Response(ToolBindingSerializer(binding).data, status=status.HTTP_201_CREATED)


class ToolBindingDetailView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanConfigureTools()]

    def _agent_version(self):
        return selectors.agent_version_get_for_workspace_or_404(
            workspace=self.workspace,
            agent_id=self.kwargs["agent_id"],
            version_id=self.kwargs["version_id"],
        )

    @extend_schema(
        request=ToolBindingUpdateSerializer,
        responses={
            200: ToolBindingSerializer,
            409: OpenApiResponse(description="Version not draft."),
        },
    )
    def patch(self, request, workspace_id, agent_id, version_id, binding_id):
        agent_version = self._agent_version()
        binding = selectors.tool_binding_get_for_workspace_or_404(
            workspace=self.workspace, agent_version=agent_version, binding_id=binding_id
        )
        serializer = ToolBindingUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            binding = services.set_tool_binding_enabled(
                workspace=self.workspace,
                binding=binding,
                actor=request.user,
                enabled=serializer.validated_data["enabled"],
                request_id=_request_id(request),
            )
        except (ToolError, AgentVersionImmutableError) as exc:
            raise ConflictError(exc.safe_message) from exc
        return Response(ToolBindingSerializer(binding).data)


class ToolExecutionListView(WorkspaceScopedMixin, generics.ListAPIView):
    serializer_class = ToolExecutionSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ToolExecution.objects.none()
        return selectors.tool_execution_list_for_workspace(
            workspace=self.workspace,
            status=self.request.query_params.get("status"),
            agent_run_id=self.request.query_params.get("agent_run_id"),
        )


class ToolExecutionDetailView(WorkspaceScopedMixin, APIView):
    @extend_schema(responses=ToolExecutionSerializer)
    def get(self, request, workspace_id, execution_id):
        execution = selectors.tool_execution_get_for_workspace_or_404(
            workspace=self.workspace, execution_id=execution_id
        )
        return Response(ToolExecutionSerializer(execution).data)
