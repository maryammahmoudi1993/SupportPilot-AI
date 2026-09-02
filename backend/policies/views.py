"""Thin, workspace-scoped policy management views (section 74-75). Read
access is any active member; every mutation requires ``CanManagePolicies``
(owner/admin)."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from common.exceptions import SafeAPIError
from workspaces.permissions import IsWorkspaceMember
from workspaces.views import WorkspaceScopedMixin

from . import services
from .errors import PolicyError
from .models import Policy, PolicyVersion
from .permissions import CanManagePolicies
from .serializers import (
    PolicyCreateSerializer,
    PolicyRuleCreateSerializer,
    PolicyRuleSerializer,
    PolicySerializer,
    PolicyUpdateSerializer,
    PolicyVersionSerializer,
)


def _request_id(request) -> str | None:
    return getattr(request, "request_id", None)


def _policy_api_error(exc: PolicyError) -> SafeAPIError:
    return SafeAPIError(exc.safe_message, code=exc.code)


class PolicyListCreateView(WorkspaceScopedMixin, generics.ListCreateAPIView):
    queryset = Policy.objects.none()

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsWorkspaceMember(), CanManagePolicies()]
        return [IsWorkspaceMember()]

    def get_serializer_class(self):
        return PolicyCreateSerializer if self.request.method == "POST" else PolicySerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Policy.objects.none()
        return Policy.objects.filter(workspace=self.workspace).order_by("-created_at", "-id")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            policy = services.create_policy(
                workspace=self.workspace,
                actor=request.user,
                name=serializer.validated_data["name"],
                description=serializer.validated_data.get("description", ""),
                request_id=_request_id(request),
            )
        except PolicyError as exc:
            raise _policy_api_error(exc) from exc
        return Response(PolicySerializer(policy).data, status=status.HTTP_201_CREATED)


class PolicyDetailView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        if self.request.method == "PATCH":
            return [IsWorkspaceMember(), CanManagePolicies()]
        return [IsWorkspaceMember()]

    def _policy(self, policy_id) -> Policy:
        from django.shortcuts import get_object_or_404

        return get_object_or_404(Policy, pk=policy_id, workspace=self.workspace)

    @extend_schema(responses=PolicySerializer)
    def get(self, request, workspace_id, policy_id):
        return Response(PolicySerializer(self._policy(policy_id)).data)

    @extend_schema(request=PolicyUpdateSerializer, responses=PolicySerializer)
    def patch(self, request, workspace_id, policy_id):
        policy = self._policy(policy_id)
        serializer = PolicyUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            policy = services.update_policy(
                workspace=self.workspace,
                policy=policy,
                actor=request.user,
                name=serializer.validated_data.get("name"),
                description=serializer.validated_data.get("description"),
                request_id=_request_id(request),
            )
        except PolicyError as exc:
            raise _policy_api_error(exc) from exc
        return Response(PolicySerializer(policy).data)


class PolicyActivateView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanManagePolicies()]

    @extend_schema(request=None, responses=PolicySerializer)
    def post(self, request, workspace_id, policy_id):
        from django.shortcuts import get_object_or_404

        policy = get_object_or_404(Policy, pk=policy_id, workspace=self.workspace)
        try:
            policy = services.activate_policy(
                workspace=self.workspace,
                policy=policy,
                actor=request.user,
                request_id=_request_id(request),
            )
        except PolicyError as exc:
            raise _policy_api_error(exc) from exc
        return Response(PolicySerializer(policy).data)


class PolicyDeactivateView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanManagePolicies()]

    @extend_schema(request=None, responses=PolicySerializer)
    def post(self, request, workspace_id, policy_id):
        from django.shortcuts import get_object_or_404

        policy = get_object_or_404(Policy, pk=policy_id, workspace=self.workspace)
        try:
            policy = services.deactivate_policy(
                workspace=self.workspace,
                policy=policy,
                actor=request.user,
                request_id=_request_id(request),
            )
        except PolicyError as exc:
            raise _policy_api_error(exc) from exc
        return Response(PolicySerializer(policy).data)


class PolicyVersionListCreateView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanManagePolicies()]

    def _policy(self, policy_id) -> Policy:
        from django.shortcuts import get_object_or_404

        return get_object_or_404(Policy, pk=policy_id, workspace=self.workspace)

    @extend_schema(responses=PolicyVersionSerializer(many=True))
    def get(self, request, workspace_id, policy_id):
        policy = self._policy(policy_id)
        versions = PolicyVersion.objects.filter(policy=policy).prefetch_related("rules")
        return Response(PolicyVersionSerializer(versions, many=True).data)

    @extend_schema(request=None, responses=PolicyVersionSerializer)
    def post(self, request, workspace_id, policy_id):
        policy = self._policy(policy_id)
        version = services.create_policy_version(
            workspace=self.workspace,
            policy=policy,
            actor=request.user,
            request_id=_request_id(request),
        )
        return Response(PolicyVersionSerializer(version).data, status=status.HTTP_201_CREATED)


class PolicyVersionDetailView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanManagePolicies()]

    def _version(self, policy_id, version_id) -> PolicyVersion:
        from django.shortcuts import get_object_or_404

        return get_object_or_404(
            PolicyVersion.objects.prefetch_related("rules"),
            pk=version_id,
            policy_id=policy_id,
            policy__workspace=self.workspace,
        )

    @extend_schema(responses=PolicyVersionSerializer)
    def get(self, request, workspace_id, policy_id, version_id):
        return Response(PolicyVersionSerializer(self._version(policy_id, version_id)).data)


class PolicyVersionPublishView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanManagePolicies()]

    @extend_schema(request=None, responses=PolicyVersionSerializer)
    def post(self, request, workspace_id, policy_id, version_id):
        from django.shortcuts import get_object_or_404

        version = get_object_or_404(
            PolicyVersion, pk=version_id, policy_id=policy_id, policy__workspace=self.workspace
        )
        try:
            version = services.publish_policy_version(
                workspace=self.workspace,
                policy_version=version,
                actor=request.user,
                request_id=_request_id(request),
            )
        except PolicyError as exc:
            raise _policy_api_error(exc) from exc
        return Response(PolicyVersionSerializer(version).data)


class PolicyRuleListCreateView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanManagePolicies()]

    def _version(self, policy_id, version_id) -> PolicyVersion:
        from django.shortcuts import get_object_or_404

        return get_object_or_404(
            PolicyVersion, pk=version_id, policy_id=policy_id, policy__workspace=self.workspace
        )

    @extend_schema(responses=PolicyRuleSerializer(many=True))
    def get(self, request, workspace_id, policy_id, version_id):
        version = self._version(policy_id, version_id)
        rules = version.rules.all().order_by("priority", "id")
        return Response(PolicyRuleSerializer(rules, many=True).data)

    @extend_schema(request=PolicyRuleCreateSerializer, responses=PolicyRuleSerializer)
    def post(self, request, workspace_id, policy_id, version_id):
        version = self._version(policy_id, version_id)
        serializer = PolicyRuleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            rule = services.add_policy_rule(
                workspace=self.workspace,
                policy_version=version,
                actor=request.user,
                data=dict(serializer.validated_data),
            )
        except PolicyError as exc:
            raise _policy_api_error(exc) from exc
        return Response(PolicyRuleSerializer(rule).data, status=status.HTTP_201_CREATED)
