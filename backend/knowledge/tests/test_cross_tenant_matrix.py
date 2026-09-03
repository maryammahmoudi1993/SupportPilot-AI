"""Cross-tenant IDOR and nested-IDOR matrix for the knowledge domain (Phase
15 checkpoint 3, Part A). Every model here carries its own direct
``workspace`` FK (unlike agents/policies/evaluations), so the primary
adversarial target is the *nested* combination — a real child id (document,
ingestion job, retrieval event) whose own ``workspace`` matches, requested
through a URL for the wrong parent source — plus the ordinary top-level
cross-tenant cases."""

from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from common.tests.security_matrix import two_workspaces

from .factories import (
    KnowledgeDocumentFactory,
    KnowledgeIngestionJobFactory,
    KnowledgeSourceFactory,
)

__all__ = ["two_workspaces"]


def _client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


def _base(workspace_id) -> str:
    return f"/api/v1/workspaces/{workspace_id}/knowledge"


@pytest.mark.django_db
class TestKnowledgeSourceCrossTenant:
    def test_foreign_workspace_source_detail_is_404(self, two_workspaces):
        d = two_workspaces
        source = KnowledgeSourceFactory(workspace=d["workspace_a"])
        response = _client(d["b_owner"].user).get(
            f"{_base(d['workspace_b'].id)}/sources/{source.id}/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_foreign_workspace_source_patch_is_404_and_unchanged(self, two_workspaces):
        d = two_workspaces
        source = KnowledgeSourceFactory(workspace=d["workspace_a"], name="Original")
        response = _client(d["b_owner"].user).patch(
            f"{_base(d['workspace_b'].id)}/sources/{source.id}/",
            {"name": "Hijacked"},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        source.refresh_from_db()
        assert source.name == "Original"

    def test_source_list_never_leaks_another_tenants_source(self, two_workspaces):
        d = two_workspaces
        KnowledgeSourceFactory(workspace=d["workspace_a"], name="A-only")
        response = _client(d["b_owner"].user).get(f"{_base(d['workspace_b'].id)}/sources/")
        names = [row["name"] for row in response.data["results"]]
        assert "A-only" not in names


@pytest.mark.django_db
class TestKnowledgeDocumentCrossTenant:
    def test_foreign_workspace_document_detail_is_404(self, two_workspaces):
        d = two_workspaces
        document = KnowledgeDocumentFactory(workspace=d["workspace_a"])
        response = _client(d["b_owner"].user).get(
            f"{_base(d['workspace_b'].id)}/documents/{document.id}/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_foreign_workspace_document_retry_is_404_and_no_job_created(self, two_workspaces):
        d = two_workspaces
        from knowledge.models import KnowledgeDocumentStatus, KnowledgeIngestionJob

        document = KnowledgeDocumentFactory(
            workspace=d["workspace_a"], status=KnowledgeDocumentStatus.FAILED
        )
        job_count_before = KnowledgeIngestionJob.objects.filter(document=document).count()

        response = _client(d["b_owner"].user).post(
            f"{_base(d['workspace_b'].id)}/documents/{document.id}/retry/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert KnowledgeIngestionJob.objects.filter(document=document).count() == job_count_before
        document.refresh_from_db()
        assert document.status == KnowledgeDocumentStatus.FAILED

    def test_uploading_a_document_against_a_foreign_workspaces_source_is_rejected(
        self, two_workspaces
    ):
        """The upload view resolves ``source_id`` scoped to the caller's
        own workspace before touching storage/ingestion — a Workspace A
        source id used from Workspace B must never create a document."""
        d = two_workspaces
        from django.core.files.uploadedfile import SimpleUploadedFile

        from knowledge.models import KnowledgeDocument

        source_a = KnowledgeSourceFactory(workspace=d["workspace_a"])
        upload = SimpleUploadedFile("note.txt", b"hello world", content_type="text/plain")

        response = _client(d["b_owner"].user).post(
            f"{_base(d['workspace_b'].id)}/documents/",
            {"source_id": str(source_a.id), "title": "Smuggled doc", "file": upload},
            format="multipart",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert not KnowledgeDocument.objects.filter(source=source_a, title="Smuggled doc").exists()


@pytest.mark.django_db
class TestKnowledgeNestedIDOR:
    def test_ingestion_job_from_a_foreign_workspace_document_is_404(self, two_workspaces):
        d = two_workspaces
        document_a = KnowledgeDocumentFactory(workspace=d["workspace_a"])
        job_a = KnowledgeIngestionJobFactory(document=document_a, workspace=d["workspace_a"])

        response = _client(d["b_owner"].user).get(
            f"{_base(d['workspace_b'].id)}/ingestion-jobs/{job_a.id}/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_document_list_filtered_by_a_foreign_source_id_returns_nothing(self, two_workspaces):
        d = two_workspaces
        source_a = KnowledgeSourceFactory(workspace=d["workspace_a"])
        KnowledgeDocumentFactory(source=source_a, workspace=d["workspace_a"])

        response = _client(d["b_owner"].user).get(
            f"{_base(d['workspace_b'].id)}/documents/?source_id={source_a.id}"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["results"] == []


@pytest.mark.django_db
class TestKnowledgeRBAC:
    def test_viewer_can_read_but_not_create_source(self, two_workspaces):
        d = two_workspaces
        source = KnowledgeSourceFactory(workspace=d["workspace_a"])
        ok = _client(d["a_viewer"].user).get(f"{_base(d['workspace_a'].id)}/sources/{source.id}/")
        assert ok.status_code == status.HTTP_200_OK

        denied = _client(d["a_viewer"].user).post(
            f"{_base(d['workspace_a'].id)}/sources/", {"name": "New source"}, format="json"
        )
        assert denied.status_code == status.HTTP_403_FORBIDDEN

    def test_support_agent_cannot_retry_a_document(self, two_workspaces):
        d = two_workspaces
        from knowledge.models import KnowledgeDocumentStatus

        document = KnowledgeDocumentFactory(
            workspace=d["workspace_a"], status=KnowledgeDocumentStatus.FAILED
        )
        response = _client(d["a_agent"].user).post(
            f"{_base(d['workspace_a'].id)}/documents/{document.id}/retry/"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestKnowledgeMassAssignment:
    def test_client_cannot_set_source_workspace_or_id_on_create(self, two_workspaces):
        d = two_workspaces
        response = _client(d["a_owner"].user).post(
            f"{_base(d['workspace_a'].id)}/sources/",
            {"name": "New source", "workspace": str(d["workspace_b"].id)},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        from knowledge.models import KnowledgeSource

        source = KnowledgeSource.objects.get(pk=response.data["id"])
        assert source.workspace_id == d["workspace_a"].id
