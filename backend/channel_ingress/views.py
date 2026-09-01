"""Channel-ingress views.

Two distinct trust boundaries, kept conceptually and structurally separate
(section 44-45):

* Staff configuration views (``ChannelEndpoint*View``, ``InboundChannelEvent*View``)
  sit below the normal ``workspaces/<uuid:workspace_id>/...`` JWT+RBAC
  boundary, exactly like ``webhooks.views``.
* Public ingress views (``ChatSession*View``, ``InboundWebhookView``) are
  unauthenticated by design — ``permission_classes = [AllowAny]``,
  ``authentication_classes = []`` — and derive their own security from a
  signed request (provider webhooks) or a session capability (web chat),
  never from staff JWT/RBAC (section 45).
"""

from __future__ import annotations

from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from agents.models import AgentVersion
from common.exceptions import SafeAPIError
from common.pagination import StandardResultsSetPagination
from integrations.models import IntegrationConnection
from workspaces.permissions import IsWorkspaceMember
from workspaces.views import WorkspaceScopedMixin

from . import selectors
from .adapters import get_adapter
from .endpoint_admin import InvalidAgentVersionError
from .endpoint_admin import create_endpoint as create_channel_endpoint
from .endpoint_admin import rotate_secret as rotate_channel_secret
from .endpoint_admin import set_endpoint_status as set_channel_endpoint_status
from .endpoint_admin import update_endpoint as update_channel_endpoint
from .errors import ChannelIngressError
from .models import ChannelEndpoint, InboundChannelEvent
from .permissions import CanManageChannels
from .security import compute_payload_digest
from .serializers import (
    ChannelEndpointCreateSerializer,
    ChannelEndpointSerializer,
    ChannelEndpointStatusSerializer,
    ChannelEndpointUpdateSerializer,
    ChannelRotateSecretResponseSerializer,
    ChatMessageSerializer,
    ChatMessageSubmitSerializer,
    ChatSessionBootstrapResponseSerializer,
    InboundChannelEventSerializer,
)
from .webchat import (
    bootstrap_chat_session,
    list_chat_messages,
    require_session,
    submit_chat_message,
)


def _request_id(request) -> str | None:
    return getattr(request, "request_id", None)


def _channel_api_error(exc: ChannelIngressError) -> SafeAPIError:
    return SafeAPIError(exc.safe_message, code=exc.code)


# ---------------------------------------------------------------------------
# Staff configuration
# ---------------------------------------------------------------------------


def _reveal_secret_once(endpoint: ChannelEndpoint, plaintext_secret: str | None) -> dict:
    data = ChannelEndpointSerializer(endpoint).data
    data["signing_secret"] = plaintext_secret
    return data


class ChannelEndpointListCreateView(WorkspaceScopedMixin, generics.ListCreateAPIView):
    queryset = ChannelEndpoint.objects.none()
    pagination_class = StandardResultsSetPagination

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsWorkspaceMember(), CanManageChannels()]
        return [IsWorkspaceMember()]

    def get_serializer_class(self):
        return (
            ChannelEndpointCreateSerializer
            if self.request.method == "POST"
            else ChannelEndpointSerializer
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ChannelEndpoint.objects.none()
        return selectors.endpoint_list_for_workspace(workspace=self.workspace)

    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        agent_version = AgentVersion.objects.filter(
            pk=data["agent_version_id"], agent_definition__workspace=self.workspace
        ).first()
        if agent_version is None:
            raise Http404("Agent version not found.")

        integration_connection = None
        connection_id = data.get("integration_connection_id")
        if connection_id:
            integration_connection = IntegrationConnection.objects.filter(
                pk=connection_id, workspace=self.workspace
            ).first()
            if integration_connection is None:
                raise Http404("Integration connection not found.")

        try:
            endpoint, plaintext_secret = create_channel_endpoint(
                workspace=self.workspace,
                actor=request.user,
                channel=data["channel"],
                name=data["name"],
                agent_version=agent_version,
                integration_connection=integration_connection,
                unknown_customer_policy=data["unknown_customer_policy"],
                configuration=data.get("configuration") or {},
                request_id=_request_id(request),
            )
        except InvalidAgentVersionError as exc:
            raise SafeAPIError(str(exc), code="invalid_agent_version") from exc
        return Response(
            _reveal_secret_once(endpoint, plaintext_secret), status=status.HTTP_201_CREATED
        )


class ChannelEndpointDetailView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        if self.request.method == "PATCH":
            return [IsWorkspaceMember(), CanManageChannels()]
        return [IsWorkspaceMember()]

    def _endpoint(self, endpoint_id) -> ChannelEndpoint:
        return selectors.endpoint_get_for_workspace_or_404(
            workspace=self.workspace, endpoint_id=endpoint_id
        )

    @extend_schema(responses=ChannelEndpointSerializer)
    def get(self, request, workspace_id, endpoint_id):
        return Response(ChannelEndpointSerializer(self._endpoint(endpoint_id)).data)

    @extend_schema(request=ChannelEndpointUpdateSerializer, responses=ChannelEndpointSerializer)
    def patch(self, request, workspace_id, endpoint_id):
        endpoint = self._endpoint(endpoint_id)
        serializer = ChannelEndpointUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        agent_version = None
        if "agent_version_id" in data:
            agent_version = AgentVersion.objects.filter(
                pk=data["agent_version_id"], agent_definition__workspace=self.workspace
            ).first()
            if agent_version is None:
                raise Http404("Agent version not found.")

        try:
            endpoint = update_channel_endpoint(
                workspace=self.workspace,
                endpoint=endpoint,
                actor=request.user,
                name=data.get("name"),
                agent_version=agent_version,
                unknown_customer_policy=data.get("unknown_customer_policy"),
                configuration=data.get("configuration"),
                request_id=_request_id(request),
            )
        except InvalidAgentVersionError as exc:
            raise SafeAPIError(str(exc), code="invalid_agent_version") from exc
        return Response(ChannelEndpointSerializer(endpoint).data)


class ChannelEndpointStatusView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanManageChannels()]

    @extend_schema(request=ChannelEndpointStatusSerializer, responses=ChannelEndpointSerializer)
    def patch(self, request, workspace_id, endpoint_id):
        endpoint = selectors.endpoint_get_for_workspace_or_404(
            workspace=self.workspace, endpoint_id=endpoint_id
        )
        serializer = ChannelEndpointStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        endpoint = set_channel_endpoint_status(
            workspace=self.workspace,
            endpoint=endpoint,
            actor=request.user,
            status=serializer.validated_data["status"],
            request_id=_request_id(request),
        )
        return Response(ChannelEndpointSerializer(endpoint).data)


class ChannelEndpointRotateSecretView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanManageChannels()]

    @extend_schema(request=None, responses=ChannelRotateSecretResponseSerializer)
    def post(self, request, workspace_id, endpoint_id):
        endpoint = selectors.endpoint_get_for_workspace_or_404(
            workspace=self.workspace, endpoint_id=endpoint_id
        )
        try:
            endpoint, plaintext_secret = rotate_channel_secret(
                workspace=self.workspace,
                endpoint=endpoint,
                actor=request.user,
                request_id=_request_id(request),
            )
        except ValueError as exc:
            raise SafeAPIError(str(exc), code="invalid_request") from exc
        return Response(
            ChannelRotateSecretResponseSerializer({"signing_secret": plaintext_secret}).data
        )


class InboundChannelEventListView(WorkspaceScopedMixin, generics.ListAPIView):
    queryset = InboundChannelEvent.objects.none()
    serializer_class = InboundChannelEventSerializer
    pagination_class = StandardResultsSetPagination

    def get_permissions(self):
        return [IsWorkspaceMember()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return InboundChannelEvent.objects.none()
        return selectors.inbound_event_list_for_workspace(workspace=self.workspace)


class InboundChannelEventDetailView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember()]

    @extend_schema(responses=InboundChannelEventSerializer)
    def get(self, request, workspace_id, event_id):
        event = selectors.inbound_event_get_for_workspace(
            workspace=self.workspace, event_id=event_id
        )
        if event is None:
            raise Http404("Inbound channel event not found.")
        return Response(InboundChannelEventSerializer(event).data)


# ---------------------------------------------------------------------------
# Public ingress (section 16-18, 19-22, 45)
# ---------------------------------------------------------------------------


class ChatSessionBootstrapView(APIView):
    """Public: creates a new anonymous web-chat session. ``endpoint_id`` is
    the endpoint's public routing identifier — it selects *which* widget
    configuration applies, never an authorization grant onto arbitrary
    workspace data (section 15, 17)."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "channel_webchat_session"

    @extend_schema(request=None, responses=ChatSessionBootstrapResponseSerializer)
    def post(self, request, endpoint_id):
        endpoint = ChannelEndpoint.objects.filter(pk=endpoint_id).first()
        if endpoint is None:
            raise Http404("Channel endpoint not found.")
        try:
            session, token = bootstrap_chat_session(endpoint=endpoint)
        except ChannelIngressError as exc:
            raise _channel_api_error(exc) from exc
        return Response(
            ChatSessionBootstrapResponseSerializer(
                {"session_token": token, "expires_at": session.expires_at}
            ).data,
            status=status.HTTP_201_CREATED,
        )


class ChatMessageListCreateView(APIView):
    """Public, session-scoped: submit a customer message or retrieve the
    conversation's messages so far. Authenticated by the opaque session
    token in the URL — never a staff JWT (section 45, 58)."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "channel_webchat_message"

    @extend_schema(request=ChatMessageSubmitSerializer)
    def post(self, request, session_token):
        try:
            session = require_session(token=session_token)
        except ChannelIngressError as exc:
            raise _channel_api_error(exc) from exc

        serializer = ChatMessageSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            event = submit_chat_message(
                session=session,
                client_message_id=serializer.validated_data["client_message_id"],
                body=serializer.validated_data["body"],
            )
        except ChannelIngressError as exc:
            raise _channel_api_error(exc) from exc
        return Response({"accepted": True, "message_id": event.id}, status=status.HTTP_202_ACCEPTED)

    @extend_schema(responses=ChatMessageSerializer(many=True))
    def get(self, request, session_token):
        try:
            session = require_session(token=session_token)
        except ChannelIngressError as exc:
            raise _channel_api_error(exc) from exc
        after = request.query_params.get("after")
        messages = list_chat_messages(session=session, after=after)
        return Response(ChatMessageSerializer(messages, many=True).data)


class InboundWebhookView(APIView):
    """Public: a signed provider webhook (generic or email-style, section
    19). Authenticated entirely by the endpoint's signing secret — never
    staff JWT/RBAC (section 45)."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "channel_inbound_webhook"

    @extend_schema(request=None, responses=None)
    def post(self, request, endpoint_id):
        endpoint = ChannelEndpoint.objects.filter(pk=endpoint_id).first()
        if endpoint is None:
            # Section 53: a nonexistent endpoint id and a disabled one are
            # deliberately indistinguishable to the caller.
            raise Http404()
        if not endpoint.enabled:
            raise Http404()

        raw_body = request.body
        adapter = get_adapter(endpoint.channel)
        try:
            adapter.verify_signature(endpoint=endpoint, raw_body=raw_body, headers=request.headers)
        except ChannelIngressError as exc:
            from observability.metrics import observe_channel_signature_failure

            try:
                observe_channel_signature_failure(channel=endpoint.channel)
            except Exception:  # noqa: BLE001 - telemetry must fail open
                pass
            raise _channel_api_error(exc) from exc

        try:
            parsed = adapter.parse_event(raw_body=raw_body)
            canonical = adapter.normalize(endpoint=endpoint, parsed=parsed)
        except ChannelIngressError as exc:
            raise _channel_api_error(exc) from exc

        from .services import ingest_channel_event

        try:
            event = ingest_channel_event(
                endpoint=endpoint,
                provider_event_id=canonical.provider_event_id,
                payload_digest=compute_payload_digest(raw_body),
                external_identity=canonical.external_identity,
                body=canonical.body,
                subject=canonical.subject,
                provider_thread_id=canonical.provider_thread_id,
                provider_message_id=canonical.provider_message_id,
            )
        except ChannelIngressError as exc:
            raise _channel_api_error(exc) from exc

        # Section 53: an authenticated valid duplicate is an idempotent
        # accept, never a server failure.
        return Response({"accepted": True, "event_id": event.id}, status=status.HTTP_202_ACCEPTED)
