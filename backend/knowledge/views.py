"""Thin workspace-scoped knowledge management and retrieval views."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from common.exceptions import SafeAPIError
from workspaces.permissions import IsWorkspaceMember
from workspaces.views import WorkspaceScopedMixin

from . import selectors, services
from .errors import KnowledgeError
from .models import KnowledgeDocument, KnowledgeSource
from .permissions import CanManageKnowledge
from .retrieval.services import search_knowledge
from .serializers import (
    KnowledgeDocumentSerializer,
    KnowledgeDocumentUploadResponseSerializer,
    KnowledgeDocumentUploadSerializer,
    KnowledgeIngestionJobSerializer,
    KnowledgeSearchRequestSerializer,
    KnowledgeSearchResponseSerializer,
    KnowledgeSourceSerializer,
    KnowledgeSourceWriteSerializer,
)


def _request_id(request) -> str | None:
    return getattr(request, "request_id", None)


def _as_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes"}


class KnowledgeSourceListCreateView(WorkspaceScopedMixin, generics.ListCreateAPIView):
    queryset = KnowledgeSource.objects.none()

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsWorkspaceMember(), CanManageKnowledge()]
        return [IsWorkspaceMember()]

    def get_serializer_class(self):
        return (
            KnowledgeSourceWriteSerializer
            if self.request.method == "POST"
            else KnowledgeSourceSerializer
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return KnowledgeSource.objects.none()
        return selectors.source_list_for_workspace(
            workspace=self.workspace,
            search=self.request.query_params.get("search"),
            is_active=_as_bool(self.request.query_params.get("is_active")),
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        source = services.create_source(
            workspace=self.workspace,
            actor=request.user,
            data=serializer.validated_data,
            request_id=_request_id(request),
        )
        return Response(KnowledgeSourceSerializer(source).data, status=status.HTTP_201_CREATED)


class KnowledgeSourceDetailView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        if self.request.method in {"PATCH", "PUT"}:
            return [IsWorkspaceMember(), CanManageKnowledge()]
        return [IsWorkspaceMember()]

    @extend_schema(responses=KnowledgeSourceSerializer)
    def get(self, request, workspace_id, source_id):
        source = selectors.source_get_for_workspace_or_404(
            workspace=self.workspace, source_id=source_id
        )
        return Response(KnowledgeSourceSerializer(source).data)

    @extend_schema(request=KnowledgeSourceWriteSerializer, responses=KnowledgeSourceSerializer)
    def patch(self, request, workspace_id, source_id):
        source = selectors.source_get_for_workspace_or_404(
            workspace=self.workspace, source_id=source_id
        )
        serializer = KnowledgeSourceWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        source = services.update_source(
            workspace=self.workspace,
            source=source,
            actor=request.user,
            data=serializer.validated_data,
            request_id=_request_id(request),
        )
        return Response(KnowledgeSourceSerializer(source).data)


class KnowledgeDocumentListCreateView(WorkspaceScopedMixin, generics.ListCreateAPIView):
    queryset = KnowledgeDocument.objects.none()

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsWorkspaceMember(), CanManageKnowledge()]
        return [IsWorkspaceMember()]

    def get_serializer_class(self):
        return (
            KnowledgeDocumentUploadSerializer
            if self.request.method == "POST"
            else KnowledgeDocumentSerializer
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return KnowledgeDocument.objects.none()
        return selectors.document_list_for_workspace(
            workspace=self.workspace,
            source_id=self.request.query_params.get("source_id"),
            status=self.request.query_params.get("status"),
        )

    @extend_schema(
        request=KnowledgeDocumentUploadSerializer,
        responses={201: KnowledgeDocumentUploadResponseSerializer},
        description="Upload a UTF-8 text, Markdown, or text-based PDF document (maximum 10 MiB).",
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        source = selectors.source_get_for_workspace_or_404(
            workspace=self.workspace, source_id=serializer.validated_data["source_id"]
        )
        try:
            document, job = services.upload_document(
                workspace=self.workspace,
                source=source,
                actor=request.user,
                title=serializer.validated_data["title"],
                upload=serializer.validated_data["file"],
                metadata=serializer.validated_data.get("metadata"),
                request_id=_request_id(request),
            )
        except KnowledgeError as exc:
            raise SafeAPIError(exc.safe_message, code=exc.code) from exc
        payload = {
            "document": KnowledgeDocumentSerializer(document).data,
            "ingestion_job": KnowledgeIngestionJobSerializer(job).data,
        }
        return Response(payload, status=status.HTTP_201_CREATED)


class KnowledgeDocumentDetailView(WorkspaceScopedMixin, APIView):
    @extend_schema(responses=KnowledgeDocumentSerializer)
    def get(self, request, workspace_id, document_id):
        document = selectors.document_get_for_workspace_or_404(
            workspace=self.workspace, document_id=document_id
        )
        return Response(KnowledgeDocumentSerializer(document).data)


class KnowledgeDocumentRetryView(WorkspaceScopedMixin, APIView):
    def get_permissions(self):
        return [IsWorkspaceMember(), CanManageKnowledge()]

    @extend_schema(
        request=None,
        responses={
            202: KnowledgeIngestionJobSerializer,
            409: OpenApiResponse(description="Not failed."),
        },
    )
    def post(self, request, workspace_id, document_id):
        document = selectors.document_get_for_workspace_or_404(
            workspace=self.workspace, document_id=document_id
        )
        job = services.retry_document(
            workspace=self.workspace,
            document=document,
            actor=request.user,
            request_id=_request_id(request),
        )
        return Response(KnowledgeIngestionJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


class KnowledgeIngestionJobDetailView(WorkspaceScopedMixin, APIView):
    @extend_schema(responses=KnowledgeIngestionJobSerializer)
    def get(self, request, workspace_id, job_id):
        job = selectors.ingestion_job_get_for_workspace_or_404(
            workspace=self.workspace, job_id=job_id
        )
        return Response(KnowledgeIngestionJobSerializer(job).data)


def _search_response(result) -> dict:
    return {
        "event_id": result.event_id,
        "query": result.query,
        "sufficient_context": result.sufficient_context,
        "results": [
            {
                "chunk_id": item.chunk_id,
                "document_id": item.document_id,
                "document_title": item.document_title,
                "source_id": item.source_id,
                "source_name": item.source_name,
                "rank": item.rank,
                "score": item.score,
                "text": item.text,
                "citation": item.citation.as_dict(),
            }
            for item in result.results
        ],
    }


class KnowledgeSearchView(WorkspaceScopedMixin, APIView):
    @extend_schema(
        request=KnowledgeSearchRequestSerializer,
        responses=KnowledgeSearchResponseSerializer,
        description="Workspace-scoped cosine search over active, ready knowledge documents.",
    )
    def post(self, request, workspace_id):
        serializer = KnowledgeSearchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = search_knowledge(
                workspace=self.workspace,
                actor=request.user,
                **serializer.validated_data,
            )
        except KnowledgeError as exc:
            raise SafeAPIError(exc.safe_message, code=exc.code) from exc
        return Response(_search_response(result))


class RetrievalEventDetailView(WorkspaceScopedMixin, APIView):
    """Read persisted retrieval provenance without exposing storage internals."""

    @extend_schema(responses=KnowledgeSearchResponseSerializer)
    def get(self, request, workspace_id, event_id):
        event = selectors.retrieval_event_get_for_workspace_or_404(
            workspace=self.workspace, event_id=event_id
        )
        hits = event.hits.select_related("chunk", "chunk__document", "chunk__document__source")
        return Response(
            {
                "event_id": event.id,
                "query": event.query,
                "sufficient_context": event.result_count > 0,
                "results": [
                    {
                        "chunk_id": hit.chunk_id,
                        "document_id": hit.chunk.document_id,
                        "document_title": hit.chunk.document.title,
                        "source_id": hit.chunk.document.source_id,
                        "source_name": hit.chunk.document.source.name,
                        "rank": hit.rank,
                        "score": hit.score,
                        "text": hit.chunk.text,
                        "citation": hit.citation,
                    }
                    for hit in hits
                ],
            }
        )
