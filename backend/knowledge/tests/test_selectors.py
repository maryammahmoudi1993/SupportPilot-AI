import pytest
from django.http import Http404

from knowledge import selectors
from knowledge.models import KnowledgeDocumentStatus, RetrievalEvent
from workspaces.tests.factories import WorkspaceFactory

from .factories import (
    KnowledgeDocumentFactory,
    KnowledgeIngestionJobFactory,
    KnowledgeSourceFactory,
)


@pytest.mark.django_db
class TestKnowledgeSelectors:
    def test_source_list_filters_search_and_active(self):
        workspace = WorkspaceFactory()
        match = KnowledgeSourceFactory(workspace=workspace, name="Refund policies", is_active=True)
        KnowledgeSourceFactory(workspace=workspace, name="Shipping", is_active=False)
        KnowledgeSourceFactory(name="Foreign refund")
        assert list(
            selectors.source_list_for_workspace(
                workspace=workspace, search="refund", is_active=True
            )
        ) == [match]

    def test_source_detail_is_tenant_scoped(self):
        with pytest.raises(Http404):
            selectors.source_get_for_workspace_or_404(
                workspace=WorkspaceFactory(), source_id=KnowledgeSourceFactory().id
            )

    def test_document_list_filters_source_status_and_invalid_id(self):
        workspace = WorkspaceFactory()
        source = KnowledgeSourceFactory(workspace=workspace)
        ready = KnowledgeDocumentFactory(workspace=workspace, source=source)
        KnowledgeDocumentFactory(
            workspace=workspace,
            source=source,
            status=KnowledgeDocumentStatus.FAILED,
        )
        assert list(
            selectors.document_list_for_workspace(
                workspace=workspace, source_id=source.id, status=KnowledgeDocumentStatus.READY
            )
        ) == [ready]
        assert not selectors.document_list_for_workspace(
            workspace=workspace, source_id="invalid"
        ).exists()

    def test_document_job_and_event_detail_are_tenant_scoped(self):
        document = KnowledgeDocumentFactory()
        job = KnowledgeIngestionJobFactory(workspace=document.workspace, document=document)
        event = RetrievalEvent.objects.create(
            workspace=document.workspace,
            query="refund",
            embedding_provider="test",
            embedding_model="test",
            top_k=5,
        )
        assert (
            selectors.document_get_for_workspace_or_404(
                workspace=document.workspace, document_id=document.id
            )
            == document
        )
        assert (
            selectors.ingestion_job_get_for_workspace_or_404(
                workspace=document.workspace, job_id=job.id
            )
            == job
        )
        assert (
            selectors.retrieval_event_get_for_workspace_or_404(
                workspace=document.workspace, event_id=event.id
            )
            == event
        )
        foreign = WorkspaceFactory()
        for resolver, keyword, value in [
            (selectors.document_get_for_workspace_or_404, "document_id", document.id),
            (selectors.ingestion_job_get_for_workspace_or_404, "job_id", job.id),
            (selectors.retrieval_event_get_for_workspace_or_404, "event_id", event.id),
        ]:
            with pytest.raises(Http404):
                resolver(workspace=foreign, **{keyword: value})
