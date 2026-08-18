from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from knowledge.ingestion.embeddings import DeterministicHashEmbeddingProvider
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceFactory, WorkspaceMembershipFactory

from .factories import KnowledgeChunkFactory, KnowledgeDocumentFactory, KnowledgeSourceFactory


def _client(user=None):
    client = APIClient()
    if user:
        client.force_authenticate(user=user)
    return client


def _base(workspace):
    return f"/api/v1/workspaces/{workspace.id}/knowledge"


@pytest.mark.django_db
class TestKnowledgeSourceApi:
    def test_anonymous_is_401_and_foreign_workspace_is_404(self):
        workspace = WorkspaceFactory()
        assert _client().get(f"{_base(workspace)}/sources/").status_code == 401
        membership = WorkspaceMembershipFactory()
        assert _client(membership.user).get(f"{_base(workspace)}/sources/").status_code == 404

    @pytest.mark.parametrize(
        "role,allowed",
        [
            (WorkspaceRole.OWNER, True),
            (WorkspaceRole.ADMIN, True),
            (WorkspaceRole.SUPPORT_MANAGER, True),
            (WorkspaceRole.SUPPORT_AGENT, False),
            (WorkspaceRole.VIEWER, False),
        ],
    )
    def test_management_rbac_and_all_roles_can_read(self, role, allowed):
        membership = WorkspaceMembershipFactory(role=role)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/sources/", {"name": "Policies"}, format="json"
        )
        assert response.status_code == (201 if allowed else 403)
        assert (
            _client(membership.user).get(f"{_base(membership.workspace)}/sources/").status_code
            == 200
        )

    def test_source_detail_is_tenant_scoped(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.VIEWER)
        foreign = KnowledgeSourceFactory()
        response = _client(membership.user).get(
            f"{_base(membership.workspace)}/sources/{foreign.id}/"
        )
        assert response.status_code == 404

    def test_manager_gets_updates_and_filters_sources(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_MANAGER)
        source = KnowledgeSourceFactory(workspace=membership.workspace, name="Refund policies")
        client = _client(membership.user)
        detail = f"{_base(membership.workspace)}/sources/{source.id}/"
        assert client.get(detail).data["name"] == "Refund policies"
        response = client.patch(detail, {"description": "Updated"}, format="json")
        assert response.status_code == 200
        assert response.data["description"] == "Updated"
        listed = client.get(
            f"{_base(membership.workspace)}/sources/", {"search": "refund", "is_active": "true"}
        )
        assert listed.data["count"] == 1


@pytest.mark.django_db
class TestKnowledgeDocumentApi:
    def test_manager_uploads_multipart_and_internal_fields_are_ignored(self, tmp_path, settings):
        settings.MEDIA_ROOT = tmp_path
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_MANAGER)
        source = KnowledgeSourceFactory(workspace=membership.workspace)
        with patch("knowledge.services._dispatch_ingestion"):
            response = _client(membership.user).post(
                f"{_base(membership.workspace)}/documents/",
                {
                    "source_id": str(source.id),
                    "title": "Policy",
                    "file": SimpleUploadedFile(
                        "policy.txt", b"Refund policy", content_type="text/plain"
                    ),
                    "workspace": str(WorkspaceFactory().id),
                    "status": "ready",
                    "chunk_count": 999,
                },
                format="multipart",
            )
        assert response.status_code == 201
        assert response.data["document"]["status"] == "queued"
        assert response.data["document"]["chunk_count"] == 0

    @pytest.mark.parametrize("role", [WorkspaceRole.SUPPORT_AGENT, WorkspaceRole.VIEWER])
    def test_read_only_roles_cannot_upload(self, role):
        membership = WorkspaceMembershipFactory(role=role)
        source = KnowledgeSourceFactory(workspace=membership.workspace)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/documents/",
            {
                "source_id": str(source.id),
                "title": "Policy",
                "file": SimpleUploadedFile("policy.txt", b"content", content_type="text/plain"),
            },
            format="multipart",
        )
        assert response.status_code == 403

    def test_fake_pdf_returns_stable_safe_error(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        source = KnowledgeSourceFactory(workspace=membership.workspace)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/documents/",
            {
                "source_id": str(source.id),
                "title": "Bad",
                "file": SimpleUploadedFile(
                    "bad.pdf", b"%PDF-broken", content_type="application/pdf"
                ),
            },
            format="multipart",
        )
        assert response.status_code == 400
        assert response.data["error"]["code"] == "knowledge_malformed_pdf"
        assert "pypdf" not in str(response.data).lower()

    def test_foreign_source_upload_is_404(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        foreign = KnowledgeSourceFactory()
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/documents/",
            {
                "source_id": str(foreign.id),
                "title": "Policy",
                "file": SimpleUploadedFile("policy.txt", b"content", content_type="text/plain"),
            },
            format="multipart",
        )
        assert response.status_code == 404

    def test_document_and_ingestion_job_foreign_ids_are_404(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.VIEWER)
        foreign_doc = KnowledgeDocumentFactory()
        foreign_job = foreign_doc.ingestion_jobs.create(
            workspace=foreign_doc.workspace, idempotency_key="foreign-job"
        )
        client = _client(membership.user)
        assert (
            client.get(f"{_base(membership.workspace)}/documents/{foreign_doc.id}/").status_code
            == 404
        )
        assert (
            client.get(
                f"{_base(membership.workspace)}/ingestion-jobs/{foreign_job.id}/"
            ).status_code
            == 404
        )

    def test_role_demotion_takes_effect_without_new_token(self, tmp_path, settings):
        settings.MEDIA_ROOT = tmp_path
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_MANAGER)
        source = KnowledgeSourceFactory(workspace=membership.workspace)
        client = _client(membership.user)
        membership.role = WorkspaceRole.VIEWER
        membership.save()
        response = client.post(
            f"{_base(membership.workspace)}/documents/",
            {
                "source_id": str(source.id),
                "title": "Policy",
                "file": SimpleUploadedFile("policy.txt", b"content", content_type="text/plain"),
            },
            format="multipart",
        )
        assert response.status_code == 403

    def test_member_lists_filters_and_gets_document_and_job(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.VIEWER)
        source = KnowledgeSourceFactory(workspace=membership.workspace)
        document = KnowledgeDocumentFactory(workspace=membership.workspace, source=source)
        job = document.ingestion_jobs.create(
            workspace=membership.workspace, idempotency_key="own-job"
        )
        client = _client(membership.user)
        listed = client.get(
            f"{_base(membership.workspace)}/documents/",
            {"source_id": str(source.id), "status": "ready"},
        )
        assert listed.data["count"] == 1
        assert client.get(f"{_base(membership.workspace)}/documents/{document.id}/").data[
            "id"
        ] == str(document.id)
        assert client.get(f"{_base(membership.workspace)}/ingestion-jobs/{job.id}/").data[
            "id"
        ] == str(job.id)

    def test_manager_retries_failed_document(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_MANAGER)
        source = KnowledgeSourceFactory(workspace=membership.workspace)
        document = KnowledgeDocumentFactory(
            workspace=membership.workspace, source=source, status="failed"
        )
        document.ingestion_jobs.create(
            workspace=membership.workspace,
            idempotency_key="failed-job",
            status="failed",
        )
        with patch("knowledge.services._dispatch_ingestion"):
            response = _client(membership.user).post(
                f"{_base(membership.workspace)}/documents/{document.id}/retry/"
            )
        assert response.status_code == 202
        assert response.data["status"] == "queued"


@pytest.mark.django_db
class TestKnowledgeSearchApi:
    def test_viewer_can_search_and_receive_citation(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.VIEWER)
        source = KnowledgeSourceFactory(workspace=membership.workspace, name="Refunds")
        document = KnowledgeDocumentFactory(
            workspace=membership.workspace, source=source, title="Refund policy"
        )
        text = "Duplicate card payments can be refunded after verification."
        chunk = KnowledgeChunkFactory(
            workspace=membership.workspace,
            document=document,
            ordinal=0,
            text=text,
            end_offset=len(text),
            embedding=DeterministicHashEmbeddingProvider().embed_query(text),
        )
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/search/",
            {"query": "duplicate payment refund"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["results"][0]["chunk_id"] == chunk.id
        assert response.data["results"][0]["citation"]["chunk_ordinal"] == 0
        history = _client(membership.user).get(
            f"{_base(membership.workspace)}/retrieval-events/{response.data['event_id']}/"
        )
        assert history.status_code == 200
        assert history.data["results"][0]["chunk_id"] == chunk.id

    def test_unbounded_top_k_is_rejected(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.VIEWER)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/search/",
            {"query": "refund", "top_k": 999},
            format="json",
        )
        assert response.status_code == 400

    def test_foreign_retrieval_event_is_404(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.VIEWER)
        foreign_workspace = WorkspaceFactory()
        from knowledge.models import RetrievalEvent

        event = RetrievalEvent.objects.create(
            workspace=foreign_workspace,
            query="secret",
            embedding_provider="test",
            embedding_model="test",
            top_k=5,
        )
        response = _client(membership.user).get(
            f"{_base(membership.workspace)}/retrieval-events/{event.id}/"
        )
        assert response.status_code == 404
