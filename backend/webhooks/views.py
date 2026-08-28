"""Thin workspace-scoped webhook endpoint/delivery management views
(section 36, 40, 42-44). Read access is any active member (safe,
secret-free output); every mutation requires ``CanManageWebhooks``
(support_manager/admin/owner)."""

from __future__ import annotations

from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from common.exceptions import SafeAPIError
from common.pagination import StandardResultsSetPagination
from workspaces.permissions import IsWorkspaceMember
from workspaces.views import WorkspaceScopedMixin

from . import selectors, services
from .errors import WebhookError
from .models import WebhookDelivery, WebhookEndpoint
from .permissions import CanManageWebhooks
from .serializers import (
    WebhookDeliverySerializer,
    WebhookEndpointCreateResponseSerializer,
    WebhookEndpointCreateSerializer,
    WebhookEndpointSerializer,
    WebhookEndpointStatusSerializer,
    WebhookEndpointUpdateSerializer,
    WebhookRotateSecretResponseSerializer,
)


def _reveal_secret_once(endpoint: WebhookEndpoint, plaintext_secret: str) -> dict:
    """Merges the safe, model-bound representation with the plaintext
    secret — never a model attribute, so never returned by any other view
    (section 13, 37)."""
    data = WebhookEndpointSerializer(endpoint).data
    data["signing_secret"] = plaintext_secret
    return data


def _request_id(request) -> str | None:
    return getattr(request, "request_id", None)


def _webhook_api_error(exc: WebhookError) -> SafeAPIError:
    return SafeAPIError(exc.safe_message, code=exc.code)


class WebhookEndpointListCreateView(WorkspaceScopedMixin, generics.ListCreateAPIView):
    queryset = WebhookEndpoint.objects.none()
    pagination_class = StandardResultsSetPagination

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsWorkspaceMember(), CanManageWebhooks()]
        return [IsWorkspaceMember()]

    def get_serializer_class(self):
        return (
            WebhookEndpointCreateSerializer
            if self.request.method == "POST"
            else WebhookEndpointSerializer
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return WebhookEndpoint.objects.none()
        return selectors.endpoint_list_for_workspace(workspace=self.workspace)

    # drf-spectacular resolves a plain (non-ViewSet) APIView's per-operation
    # schema via ``getattr(view, method.lower())`` — literally the
    # HTTP-verb-named method — not the semantic CRUD action name. Decorating
    # ``create()`` alone is therefore silently ignored for a POST here: the
    # actual dispatch target DRF's ``CreateModelMixin`` wires up for POST is
    # its own inherited, undecorated ``post()``, which only delegates to
    # ``create()``. Verified directly against the generated schema (a real
    # Block 6 defect: the create endpoint's documented response silently
    # fell back to the *request* serializer shape) — the fix is to decorate
    # ``post`` itself, not ``create``.
    @extend_schema(
        request=WebhookEndpointCreateSerializer, responses=WebhookEndpointCreateResponseSerializer
    )
    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            endpoint, plaintext_secret = services.create_endpoint(
                workspace=self.workspace,
                actor=request.user,
                name=serializer.validated_data["name"],
                url=serializer.validated_data["url"],
                subscribed_event_types=serializer.validated_data["subscribed_event_types"],
                request_id=_request_id(request),
            )
        except WebhookError as exc:
            raise _webhook_api_error(exc) from exc
        return Response(
            _reveal_secret_once(endpoint, plaintext_secret), status=status.HTTP_201_CREATED
        )


class WebhookEndpointDetailView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        if self.request.method == "PATCH":
            return [IsWorkspaceMember(), CanManageWebhooks()]
        return [IsWorkspaceMember()]

    def _endpoint(self, endpoint_id) -> WebhookEndpoint:
        endpoint = selectors.endpoint_get_for_workspace(
            workspace=self.workspace, endpoint_id=endpoint_id
        )
        if endpoint is None:
            raise Http404("Webhook endpoint not found.")
        return endpoint

    @extend_schema(responses=WebhookEndpointSerializer)
    def get(self, request, workspace_id, endpoint_id):
        endpoint = self._endpoint(endpoint_id)
        return Response(WebhookEndpointSerializer(endpoint).data)

    @extend_schema(request=WebhookEndpointUpdateSerializer, responses=WebhookEndpointSerializer)
    def patch(self, request, workspace_id, endpoint_id):
        endpoint = self._endpoint(endpoint_id)
        serializer = WebhookEndpointUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            endpoint = services.update_endpoint(
                workspace=self.workspace,
                endpoint=endpoint,
                actor=request.user,
                name=serializer.validated_data.get("name"),
                url=serializer.validated_data.get("url"),
                subscribed_event_types=serializer.validated_data.get("subscribed_event_types"),
                request_id=_request_id(request),
            )
        except WebhookError as exc:
            raise _webhook_api_error(exc) from exc
        return Response(WebhookEndpointSerializer(endpoint).data)


class WebhookEndpointStatusView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanManageWebhooks()]

    @extend_schema(request=WebhookEndpointStatusSerializer, responses=WebhookEndpointSerializer)
    def patch(self, request, workspace_id, endpoint_id):
        endpoint = selectors.endpoint_get_for_workspace(
            workspace=self.workspace, endpoint_id=endpoint_id
        )
        if endpoint is None:
            raise Http404("Webhook endpoint not found.")
        serializer = WebhookEndpointStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        endpoint = services.set_endpoint_status(
            workspace=self.workspace,
            endpoint=endpoint,
            actor=request.user,
            status=serializer.validated_data["status"],
            request_id=_request_id(request),
        )
        return Response(WebhookEndpointSerializer(endpoint).data)


class WebhookEndpointRotateSecretView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanManageWebhooks()]

    @extend_schema(request=None, responses=WebhookRotateSecretResponseSerializer)
    def post(self, request, workspace_id, endpoint_id):
        endpoint = selectors.endpoint_get_for_workspace(
            workspace=self.workspace, endpoint_id=endpoint_id
        )
        if endpoint is None:
            raise Http404("Webhook endpoint not found.")
        endpoint, plaintext_secret = services.rotate_secret(
            workspace=self.workspace,
            endpoint=endpoint,
            actor=request.user,
            request_id=_request_id(request),
        )
        return Response(
            WebhookRotateSecretResponseSerializer({"signing_secret": plaintext_secret}).data
        )


class WebhookDeliveryListView(WorkspaceScopedMixin, generics.ListAPIView):
    queryset = WebhookDelivery.objects.none()
    serializer_class = WebhookDeliverySerializer
    pagination_class = StandardResultsSetPagination

    def get_permissions(self):
        return [IsWorkspaceMember()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return WebhookDelivery.objects.none()
        return selectors.delivery_list_for_workspace(workspace=self.workspace)


class WebhookDeliveryDetailView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember()]

    @extend_schema(responses=WebhookDeliverySerializer)
    def get(self, request, workspace_id, delivery_id):
        webhook_delivery = selectors.delivery_get_for_workspace(
            workspace=self.workspace, delivery_id=delivery_id
        )
        if webhook_delivery is None:
            raise Http404("Webhook delivery not found.")
        return Response(WebhookDeliverySerializer(webhook_delivery).data)


class WebhookDeliveryRedriveView(WorkspaceScopedMixin, APIView):
    """Manual redrive for a terminal webhook delivery (Phase 10 Block 4,
    section 29, 34): an explicit ``POST`` mutation, never a ``GET`` — a
    foreign-workspace delivery id resolves to 404 (section 29), matching the
    tenant-isolation convention used everywhere else in this app."""

    def get_permissions(self):
        return [IsWorkspaceMember(), CanManageWebhooks()]

    @extend_schema(request=None, responses=WebhookDeliverySerializer)
    def post(self, request, workspace_id, delivery_id):
        webhook_delivery = selectors.delivery_get_for_workspace(
            workspace=self.workspace, delivery_id=delivery_id
        )
        if webhook_delivery is None:
            raise Http404("Webhook delivery not found.")
        try:
            services.redrive_webhook_delivery(
                workspace=self.workspace,
                webhook_delivery=webhook_delivery,
                actor=request.user,
                request_id=_request_id(request),
            )
        except WebhookError as exc:
            raise _webhook_api_error(exc) from exc
        refreshed = selectors.delivery_get_for_workspace(
            workspace=self.workspace, delivery_id=delivery_id
        )
        return Response(WebhookDeliverySerializer(refreshed).data)
