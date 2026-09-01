"""Thin workspace-scoped evaluation dataset/case/run views."""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from agents.models import AgentVersion
from common.exceptions import ConflictError, SafeAPIError
from workspaces.views import WorkspaceScopedMixin

from . import selectors, services
from .errors import EvaluationError
from .models import EvaluationCase, EvaluationDataset, EvaluationResult, EvaluationRun
from .permissions import CanManageEvaluations, CanRunEvaluations, CanViewEvaluations
from .serializers import (
    EvaluationCaseSerializer,
    EvaluationCaseWriteSerializer,
    EvaluationDatasetSerializer,
    EvaluationDatasetWriteSerializer,
    EvaluationResultSerializer,
    EvaluationRunCompareSerializer,
    EvaluationRunCreateSerializer,
    EvaluationRunSerializer,
)


def _request_id(request) -> str | None:
    return getattr(request, "request_id", None)


class EvaluationDatasetListCreateView(WorkspaceScopedMixin, generics.ListCreateAPIView):
    queryset = EvaluationDataset.objects.none()

    def get_permissions(self):
        if self.request.method == "POST":
            return [CanViewEvaluations(), CanManageEvaluations()]
        return [CanViewEvaluations()]

    def get_serializer_class(self):
        return (
            EvaluationDatasetWriteSerializer
            if self.request.method == "POST"
            else EvaluationDatasetSerializer
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return EvaluationDataset.objects.none()
        return selectors.dataset_list_for_workspace(
            workspace=self.workspace, status=self.request.query_params.get("status")
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dataset = services.create_evaluation_dataset(
            workspace=self.workspace,
            actor=request.user,
            data=serializer.validated_data,
            request_id=_request_id(request),
        )
        return Response(EvaluationDatasetSerializer(dataset).data, status=status.HTTP_201_CREATED)


class EvaluationDatasetDetailView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        if self.request.method in {"PATCH", "PUT"}:
            return [CanViewEvaluations(), CanManageEvaluations()]
        return [CanViewEvaluations()]

    @extend_schema(responses=EvaluationDatasetSerializer)
    def get(self, request, workspace_id, dataset_id):
        dataset = selectors.dataset_get_for_workspace_or_404(
            workspace=self.workspace, dataset_id=dataset_id
        )
        return Response(EvaluationDatasetSerializer(dataset).data)

    @extend_schema(request=EvaluationDatasetWriteSerializer, responses=EvaluationDatasetSerializer)
    def patch(self, request, workspace_id, dataset_id):
        dataset = selectors.dataset_get_for_workspace_or_404(
            workspace=self.workspace, dataset_id=dataset_id
        )
        serializer = EvaluationDatasetWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        dataset = services.update_evaluation_dataset(
            workspace=self.workspace,
            dataset=dataset,
            actor=request.user,
            data=serializer.validated_data,
            request_id=_request_id(request),
        )
        return Response(EvaluationDatasetSerializer(dataset).data)


class EvaluationCaseListCreateView(WorkspaceScopedMixin, generics.ListCreateAPIView):
    queryset = EvaluationCase.objects.none()

    def get_permissions(self):
        if self.request.method == "POST":
            return [CanViewEvaluations(), CanManageEvaluations()]
        return [CanViewEvaluations()]

    def get_serializer_class(self):
        return (
            EvaluationCaseWriteSerializer
            if self.request.method == "POST"
            else EvaluationCaseSerializer
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return EvaluationCase.objects.none()
        dataset = selectors.dataset_get_for_workspace_or_404(
            workspace=self.workspace, dataset_id=self.kwargs["dataset_id"]
        )
        return selectors.case_list_for_dataset(
            workspace=self.workspace,
            dataset=dataset,
            status=self.request.query_params.get("status"),
        )

    def create(self, request, *args, **kwargs):
        dataset = selectors.dataset_get_for_workspace_or_404(
            workspace=self.workspace, dataset_id=self.kwargs["dataset_id"]
        )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            case = services.create_evaluation_case(
                workspace=self.workspace,
                dataset=dataset,
                actor=request.user,
                data=serializer.validated_data,
                request_id=_request_id(request),
            )
        except DjangoValidationError as exc:
            raise SafeAPIError(str(exc), code="invalid_case") from exc
        return Response(EvaluationCaseSerializer(case).data, status=status.HTTP_201_CREATED)


class EvaluationCaseDetailView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        if self.request.method in {"PATCH", "PUT"}:
            return [CanViewEvaluations(), CanManageEvaluations()]
        return [CanViewEvaluations()]

    @extend_schema(responses=EvaluationCaseSerializer)
    def get(self, request, workspace_id, dataset_id, case_id):
        dataset = selectors.dataset_get_for_workspace_or_404(
            workspace=self.workspace, dataset_id=dataset_id
        )
        case = selectors.case_get_for_workspace_or_404(
            workspace=self.workspace, dataset=dataset, case_id=case_id
        )
        return Response(EvaluationCaseSerializer(case).data)

    @extend_schema(request=EvaluationCaseWriteSerializer, responses=EvaluationCaseSerializer)
    def patch(self, request, workspace_id, dataset_id, case_id):
        dataset = selectors.dataset_get_for_workspace_or_404(
            workspace=self.workspace, dataset_id=dataset_id
        )
        case = selectors.case_get_for_workspace_or_404(
            workspace=self.workspace, dataset=dataset, case_id=case_id
        )
        serializer = EvaluationCaseWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            case = services.update_evaluation_case(
                workspace=self.workspace,
                case=case,
                actor=request.user,
                data=serializer.validated_data,
                request_id=_request_id(request),
            )
        except DjangoValidationError as exc:
            raise SafeAPIError(str(exc), code="invalid_case") from exc
        return Response(EvaluationCaseSerializer(case).data)


class EvaluationRunListCreateView(WorkspaceScopedMixin, generics.ListCreateAPIView):
    queryset = EvaluationRun.objects.none()

    def get_permissions(self):
        if self.request.method == "POST":
            return [CanViewEvaluations(), CanRunEvaluations()]
        return [CanViewEvaluations()]

    def get_throttles(self):
        # Only the execution-triggering POST is rate-limited (Section 19-20:
        # EVALUATION_EXECUTION scope) — listing existing runs is unthrottled.
        if self.request.method == "POST":
            self.throttle_scope = "evaluation_execution"
            return [ScopedRateThrottle()]
        return super().get_throttles()

    def get_serializer_class(self):
        return (
            EvaluationRunCreateSerializer
            if self.request.method == "POST"
            else EvaluationRunSerializer
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return EvaluationRun.objects.none()
        return selectors.run_list_for_workspace(
            workspace=self.workspace,
            status=self.request.query_params.get("status"),
            dataset_id=self.request.query_params.get("dataset_id"),
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        dataset = selectors.dataset_get_for_workspace_or_404(
            workspace=self.workspace, dataset_id=data["dataset_id"]
        )
        # agent_version resolved through a workspace-scoped filter so a
        # version belonging to another workspace 404s rather than being
        # resolvable (no existence leakage across tenants).
        agent_version = AgentVersion.objects.filter(
            pk=data["agent_version_id"], agent_definition__workspace=self.workspace
        ).first()
        if agent_version is None:
            raise Http404("Agent version not found.")

        try:
            run = services.start_evaluation_run(
                workspace=self.workspace,
                actor=request.user,
                dataset=dataset,
                agent_version=agent_version,
                threshold_config=data.get("threshold_config"),
                request_id=_request_id(request),
            )
        except EvaluationError as exc:
            raise SafeAPIError(exc.safe_message, code=exc.code) from exc
        return Response(EvaluationRunSerializer(run).data, status=status.HTTP_201_CREATED)


class EvaluationRunDetailView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [CanViewEvaluations()]

    @extend_schema(responses=EvaluationRunSerializer)
    def get(self, request, workspace_id, run_id):
        run = selectors.run_get_for_workspace_or_404(workspace=self.workspace, run_id=run_id)
        return Response(EvaluationRunSerializer(run).data)


class EvaluationRunCancelView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [CanViewEvaluations(), CanRunEvaluations()]

    @extend_schema(
        request=None,
        responses={
            200: EvaluationRunSerializer,
            409: OpenApiResponse(description="Not cancellable."),
        },
    )
    def post(self, request, workspace_id, run_id):
        run = selectors.run_get_for_workspace_or_404(workspace=self.workspace, run_id=run_id)
        try:
            run = services.cancel_evaluation_run(
                workspace=self.workspace,
                run=run,
                actor=request.user,
                request_id=_request_id(request),
            )
        except EvaluationError as exc:
            raise ConflictError(exc.safe_message) from exc
        return Response(EvaluationRunSerializer(run).data)


class EvaluationResultListView(WorkspaceScopedMixin, generics.ListAPIView):
    serializer_class = EvaluationResultSerializer
    queryset = EvaluationResult.objects.none()

    def get_permissions(self):
        return [CanViewEvaluations()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return EvaluationResult.objects.none()
        run = selectors.run_get_for_workspace_or_404(
            workspace=self.workspace, run_id=self.kwargs["run_id"]
        )
        passed_param = self.request.query_params.get("passed")
        passed = None
        if passed_param is not None:
            passed = passed_param.lower() in {"true", "1"}
        return selectors.result_list_for_run(
            workspace=self.workspace,
            run=run,
            status=self.request.query_params.get("status"),
            passed=passed,
        )


class EvaluationResultDetailView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [CanViewEvaluations()]

    @extend_schema(responses=EvaluationResultSerializer)
    def get(self, request, workspace_id, run_id, result_id):
        run = selectors.run_get_for_workspace_or_404(workspace=self.workspace, run_id=run_id)
        result = selectors.result_get_for_workspace_or_404(
            workspace=self.workspace, run=run, result_id=result_id
        )
        return Response(EvaluationResultSerializer(result).data)


class EvaluationResultReplayView(WorkspaceScopedMixin, APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "evaluation_execution"

    def get_permissions(self):
        return [CanViewEvaluations(), CanRunEvaluations()]

    @extend_schema(
        request=None,
        responses={
            201: EvaluationResultSerializer,
            409: OpenApiResponse(description="Not replayable."),
        },
    )
    def post(self, request, workspace_id, run_id, result_id):
        run = selectors.run_get_for_workspace_or_404(workspace=self.workspace, run_id=run_id)
        result = selectors.result_get_for_workspace_or_404(
            workspace=self.workspace, run=run, result_id=result_id
        )
        try:
            replay = services.replay_evaluation_case(
                workspace=self.workspace,
                actor=request.user,
                result=result,
                request_id=_request_id(request),
            )
        except EvaluationError as exc:
            raise ConflictError(exc.safe_message) from exc
        return Response(EvaluationResultSerializer(replay).data, status=status.HTTP_201_CREATED)


class EvaluationRunCompareView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [CanViewEvaluations(), CanRunEvaluations()]

    @extend_schema(
        request=EvaluationRunCompareSerializer,
        responses={200: OpenApiResponse(description="Comparison result.")},
    )
    def post(self, request, workspace_id):
        serializer = EvaluationRunCompareSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        baseline_run = selectors.run_get_for_workspace_or_404(
            workspace=self.workspace, run_id=data["baseline_run_id"]
        )
        candidate_run = selectors.run_get_for_workspace_or_404(
            workspace=self.workspace, run_id=data["candidate_run_id"]
        )
        try:
            comparison = services.compare_evaluation_runs(
                workspace=self.workspace,
                baseline_run=baseline_run,
                candidate_run=candidate_run,
                actor=request.user,
                request_id=_request_id(request),
            )
        except EvaluationError as exc:
            raise SafeAPIError(exc.safe_message, code=exc.code) from exc
        return Response(comparison)
