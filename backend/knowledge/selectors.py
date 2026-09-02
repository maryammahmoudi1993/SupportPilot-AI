"""Tenant-first selectors for every knowledge-owned resource."""

from __future__ import annotations

from uuid import UUID

from django.db.models import Q, QuerySet
from django.http import Http404
from rest_framework.exceptions import ValidationError

from workspaces.models import Workspace

from .models import KnowledgeDocument, KnowledgeIngestionJob, KnowledgeSource, RetrievalEvent


def source_list_for_workspace(
    *, workspace: Workspace, search: str | None = None, is_active: bool | None = None
) -> QuerySet[KnowledgeSource]:
    queryset = KnowledgeSource.objects.filter(workspace=workspace)
    if is_active is not None:
        queryset = queryset.filter(is_active=is_active)
    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(description__icontains=search))
    return queryset.order_by("-created_at", "-id")


def source_get_for_workspace_or_404(
    *, workspace: Workspace, source_id: UUID | str
) -> KnowledgeSource:
    source = KnowledgeSource.objects.filter(workspace=workspace, pk=source_id).first()
    if source is None:
        raise Http404("Knowledge source not found.")
    return source


def document_list_for_workspace(
    *,
    workspace: Workspace,
    source_id: UUID | str | None = None,
    status: str | None = None,
) -> QuerySet[KnowledgeDocument]:
    queryset = KnowledgeDocument.objects.filter(workspace=workspace).select_related("source")
    if source_id:
        try:
            resolved_source_id = UUID(str(source_id))
        except ValueError:
            # Malformed filter must fail predictably (Section 7), not
            # silently look like an honestly-applied filter with no matches.
            raise ValidationError({"source_id": "Must be a valid UUID."}) from None
        queryset = queryset.filter(source_id=resolved_source_id)
    if status:
        queryset = queryset.filter(status=status)
    return queryset.order_by("-created_at", "-id")


def document_get_for_workspace_or_404(
    *, workspace: Workspace, document_id: UUID | str
) -> KnowledgeDocument:
    document = (
        KnowledgeDocument.objects.filter(workspace=workspace, pk=document_id)
        .select_related("source")
        .first()
    )
    if document is None:
        raise Http404("Knowledge document not found.")
    return document


def ingestion_job_get_for_workspace_or_404(
    *, workspace: Workspace, job_id: UUID | str
) -> KnowledgeIngestionJob:
    job = (
        KnowledgeIngestionJob.objects.filter(workspace=workspace, pk=job_id)
        .select_related("document")
        .first()
    )
    if job is None:
        raise Http404("Knowledge ingestion job not found.")
    return job


def retrieval_event_get_for_workspace_or_404(
    *, workspace: Workspace, event_id: UUID | str
) -> RetrievalEvent:
    event = RetrievalEvent.objects.filter(workspace=workspace, pk=event_id).first()
    if event is None:
        raise Http404("Retrieval event not found.")
    return event
