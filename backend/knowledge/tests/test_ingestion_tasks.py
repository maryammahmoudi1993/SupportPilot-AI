from types import SimpleNamespace
from unittest.mock import patch

from django.test import override_settings

from knowledge.errors import RetryableIngestionError
from knowledge.tasks import ingest_knowledge_document


def test_task_delegates_to_service():
    outcome = SimpleNamespace(status="succeeded")
    with patch("knowledge.tasks.run_ingestion", return_value=outcome) as run:
        assert ingest_knowledge_document.run("job-id") == {"status": "succeeded"}
    run.assert_called_once_with(job_id="job-id")


def test_retryable_failure_uses_celery_retry():
    task = ingest_knowledge_document
    with (
        patch("knowledge.tasks.run_ingestion", side_effect=RetryableIngestionError()),
        patch("knowledge.tasks.ingestion_attempt_count", return_value=0),
        patch.object(task, "retry", side_effect=RuntimeError("retry")) as retry,
    ):
        try:
            task.run("job-id")
        except RuntimeError:
            pass
    retry.assert_called_once()


@override_settings(KNOWLEDGE_INGESTION_MAX_ATTEMPTS=1)
def test_retry_exhaustion_marks_final_failure():
    task = ingest_knowledge_document
    with (
        patch("knowledge.tasks.run_ingestion", side_effect=RetryableIngestionError()),
        patch("knowledge.tasks.ingestion_attempt_count", return_value=1),
        patch("knowledge.tasks.fail_ingestion") as fail,
    ):
        result = task.run("job-id")
    assert result["status"] == "failed"
    fail.assert_called_once()
