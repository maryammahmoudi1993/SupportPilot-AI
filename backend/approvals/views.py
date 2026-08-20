"""Thin, workspace-scoped approval views (section 76-79). Read access (list/
detail) is any active member; approve/reject require only ``IsWorkspaceMember``
at the DRF layer — role sufficiency and self-approval are checked inside
``approvals.services.decide_approval`` against the approval's own
``required_role`` and the caller's *current* DB membership (never a static
permission class, since both depend on the specific approval object)."""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from common.exceptions import SafeAPIError
from workspaces.permissions import IsWorkspaceMember
from workspaces.views import WorkspaceScopedMixin

from . import services
from .errors import ApprovalError
from .models import ApprovalDecisionValue, ApprovalRequest, ApprovalStatus
from .serializers import ApprovalDecisionInputSerializer, ApprovalRequestSerializer


def _request_id(request) -> str | None:
    return getattr(request, "request_id", None)


class _NotFoundAPIError(SafeAPIError):
    status_code = status.HTTP_404_NOT_FOUND


class _ForbiddenAPIError(SafeAPIError):
    status_code = status.HTTP_403_FORBIDDEN


class _ConflictAPIError(SafeAPIError):
    status_code = status.HTTP_409_CONFLICT


_FORBIDDEN_CODES = frozenset({"approval_permission_denied", "approval_self_approval_forbidden"})
_CONFLICT_CODES = frozenset(
    {
        "approval_already_resolved",
        "approval_expired",
        "approval_cancelled",
        "approval_resume_conflict",
    }
)


def _approval_api_error(exc: ApprovalError) -> SafeAPIError:
    if exc.code == "approval_not_found":
        return _NotFoundAPIError(exc.safe_message, code=exc.code)
    if exc.code in _FORBIDDEN_CODES:
        return _ForbiddenAPIError(exc.safe_message, code=exc.code)
    if exc.code in _CONFLICT_CODES:
        return _ConflictAPIError(exc.safe_message, code=exc.code)
    return SafeAPIError(exc.safe_message, code=exc.code)


class ApprovalRequestListView(WorkspaceScopedMixin, generics.ListAPIView):
    """Bounded, filterable, paginated queue (section 77-78). Ordering is
    deterministic: pending-first (oldest first), so an operator's queue never
    depends on undefined database ordering."""

    serializer_class = ApprovalRequestSerializer
    queryset = ApprovalRequest.objects.none()

    def get_permissions(self):
        return [IsWorkspaceMember()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ApprovalRequest.objects.none()
        qs = (
            ApprovalRequest.objects.filter(workspace=self.workspace)
            .select_related("decision")
            .order_by("created_at")
        )
        status_filter = self.request.query_params.get("status")
        if status_filter:
            if status_filter not in ApprovalStatus.values:
                return qs.none()
            qs = qs.filter(status=status_filter)
        required_role = self.request.query_params.get("required_role")
        if required_role:
            qs = qs.filter(required_role=required_role)
        tool_key = self.request.query_params.get("tool_key")
        if tool_key:
            qs = qs.filter(safe_context__tool_key=tool_key)
        return qs


class ApprovalRequestDetailView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember()]

    @extend_schema(responses=ApprovalRequestSerializer)
    def get(self, request, workspace_id, approval_id):
        approval = get_object_or_404(
            ApprovalRequest.objects.select_related("decision"),
            pk=approval_id,
            workspace=self.workspace,
        )
        return Response(ApprovalRequestSerializer(approval).data)


class ApprovalDecisionView(WorkspaceScopedMixin, APIView):
    """Base for the approve/reject endpoints — the URL itself is the
    decision (section 116): there is no client-suppliable ``decision`` field
    anywhere in this request."""

    decision_value: str

    def get_permissions(self):
        return [IsWorkspaceMember()]

    @extend_schema(request=ApprovalDecisionInputSerializer, responses=ApprovalRequestSerializer)
    def post(self, request, workspace_id, approval_id):
        approval = get_object_or_404(ApprovalRequest, pk=approval_id, workspace=self.workspace)
        serializer = ApprovalDecisionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            approval = services.decide_approval(
                workspace=self.workspace,
                approval_request=approval,
                actor=request.user,
                actor_role=self.membership.role,
                decision=self.decision_value,
                comment=serializer.validated_data.get("comment", ""),
                request_id=_request_id(request),
            )
        except ApprovalError as exc:
            raise _approval_api_error(exc) from exc
        return Response(
            ApprovalRequestSerializer(approval).data,
            status=(
                status.HTTP_200_OK
                if approval.status != ApprovalStatus.PENDING
                else status.HTTP_202_ACCEPTED
            ),
        )


class ApprovalApproveView(ApprovalDecisionView):
    decision_value = ApprovalDecisionValue.APPROVE


class ApprovalRejectView(ApprovalDecisionView):
    decision_value = ApprovalDecisionValue.REJECT
