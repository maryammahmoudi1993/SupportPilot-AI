"""Thin workspace-scoped integration connection management views
(section 64-69). Read access is any active member (safe, secret-free
output); every mutation requires ``CanManageIntegrations`` (owner/admin).
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from common.exceptions import SafeAPIError
from workspaces.permissions import IsWorkspaceMember
from workspaces.views import WorkspaceScopedMixin

from . import selectors, services
from .errors import IntegrationError
from .models import IntegrationConnection
from .permissions import CanManageIntegrations
from .serializers import (
    IntegrationConnectionCreateSerializer,
    IntegrationConnectionEnabledSerializer,
    IntegrationConnectionSerializer,
    IntegrationConnectionTestResultSerializer,
    IntegrationConnectionUpdateSerializer,
    IntegrationCredentialRotateSerializer,
)


def _request_id(request) -> str | None:
    return getattr(request, "request_id", None)


class IntegrationConnectionListCreateView(WorkspaceScopedMixin, generics.ListCreateAPIView):
    queryset = IntegrationConnection.objects.none()

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsWorkspaceMember(), CanManageIntegrations()]
        return [IsWorkspaceMember()]

    def get_serializer_class(self):
        return (
            IntegrationConnectionCreateSerializer
            if self.request.method == "POST"
            else IntegrationConnectionSerializer
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return IntegrationConnection.objects.none()
        return selectors.connection_list_for_workspace(workspace=self.workspace)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            connection = services.create_connection(
                workspace=self.workspace,
                actor=request.user,
                provider=serializer.validated_data["provider"],
                display_name=serializer.validated_data.get("display_name", ""),
                environment=serializer.validated_data["environment"],
                credentials=serializer.validated_data["credentials"],
                configuration=serializer.validated_data.get("configuration") or {},
                request_id=_request_id(request),
            )
        except IntegrationError as exc:
            raise _integration_api_error(exc) from exc
        return Response(
            IntegrationConnectionSerializer(connection).data, status=status.HTTP_201_CREATED
        )


class IntegrationConnectionDetailView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        if self.request.method in ("PATCH",):
            return [IsWorkspaceMember(), CanManageIntegrations()]
        return [IsWorkspaceMember()]

    def _connection(self, connection_id) -> IntegrationConnection:
        return selectors.connection_get_for_workspace_or_404(
            workspace=self.workspace, connection_id=connection_id
        )

    @extend_schema(responses=IntegrationConnectionSerializer)
    def get(self, request, workspace_id, connection_id):
        connection = self._connection(connection_id)
        return Response(IntegrationConnectionSerializer(connection).data)

    @extend_schema(
        request=IntegrationConnectionUpdateSerializer, responses=IntegrationConnectionSerializer
    )
    def patch(self, request, workspace_id, connection_id):
        connection = self._connection(connection_id)
        serializer = IntegrationConnectionUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            connection = services.update_connection_configuration(
                workspace=self.workspace,
                connection=connection,
                actor=request.user,
                display_name=serializer.validated_data.get("display_name"),
                configuration=serializer.validated_data.get("configuration"),
                request_id=_request_id(request),
            )
        except IntegrationError as exc:
            raise _integration_api_error(exc) from exc
        return Response(IntegrationConnectionSerializer(connection).data)


class IntegrationConnectionCredentialsView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanManageIntegrations()]

    @extend_schema(
        request=IntegrationCredentialRotateSerializer, responses=IntegrationConnectionSerializer
    )
    def put(self, request, workspace_id, connection_id):
        connection = selectors.connection_get_for_workspace_or_404(
            workspace=self.workspace, connection_id=connection_id
        )
        serializer = IntegrationCredentialRotateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            connection = services.rotate_credentials(
                workspace=self.workspace,
                connection=connection,
                actor=request.user,
                credentials=serializer.validated_data["credentials"],
                request_id=_request_id(request),
            )
        except IntegrationError as exc:
            raise _integration_api_error(exc) from exc
        return Response(IntegrationConnectionSerializer(connection).data)


class IntegrationConnectionEnabledView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanManageIntegrations()]

    @extend_schema(
        request=IntegrationConnectionEnabledSerializer, responses=IntegrationConnectionSerializer
    )
    def patch(self, request, workspace_id, connection_id):
        connection = selectors.connection_get_for_workspace_or_404(
            workspace=self.workspace, connection_id=connection_id
        )
        serializer = IntegrationConnectionEnabledSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        connection = services.set_connection_enabled(
            workspace=self.workspace,
            connection=connection,
            actor=request.user,
            enabled=serializer.validated_data["enabled"],
            request_id=_request_id(request),
        )
        return Response(IntegrationConnectionSerializer(connection).data)


class IntegrationConnectionTestView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanManageIntegrations()]

    @extend_schema(request=None, responses=IntegrationConnectionTestResultSerializer)
    def post(self, request, workspace_id, connection_id):
        connection = selectors.connection_get_for_workspace_or_404(
            workspace=self.workspace, connection_id=connection_id
        )
        try:
            result = services.test_connection(
                workspace=self.workspace,
                connection=connection,
                actor=request.user,
                request_id=_request_id(request),
            )
        except IntegrationError as exc:
            raise _integration_api_error(exc) from exc
        return Response(IntegrationConnectionTestResultSerializer(result).data)


def _integration_api_error(exc: IntegrationError) -> SafeAPIError:
    return SafeAPIError(exc.safe_message, code=exc.code)
