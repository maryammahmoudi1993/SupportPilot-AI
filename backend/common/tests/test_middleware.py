"""Tests for the correlation-ID and structured logging middleware."""

import logging
import uuid
from unittest.mock import MagicMock

import pytest
from django.test import RequestFactory
from rest_framework.test import APIClient

from common.correlation import get_correlation_id
from common.middleware import RequestIdMiddleware


@pytest.fixture
def api_client():
    return APIClient()


@pytest.mark.django_db
class TestRequestIdMiddleware:
    def test_generates_a_request_id_when_none_supplied(self, api_client):
        response = api_client.get("/health/")

        request_id = response.headers.get("X-Request-ID")
        assert request_id is not None
        # Must be a valid UUID4 when generated locally.
        uuid.UUID(request_id)

    def test_reuses_inbound_request_id_header(self, api_client):
        inbound_id = "11111111-1111-1111-1111-111111111111"

        response = api_client.get("/health/", HTTP_X_REQUEST_ID=inbound_id)

        assert response.headers.get("X-Request-ID") == inbound_id

    def test_each_request_without_header_gets_a_distinct_id(self, api_client):
        first = api_client.get("/health/").headers.get("X-Request-ID")
        second = api_client.get("/health/").headers.get("X-Request-ID")

        assert first != second

    def test_binds_the_correlation_scope_for_the_lifetime_of_the_request(self):
        """Phase 11 Block 2: the request's id must be readable via
        ``common.correlation.get_correlation_id()`` while the response is
        being built (so anything it triggers, including a
        ``transaction.on_commit`` Celery dispatch, sees it), and unbound
        again once the middleware returns."""
        observed = {}

        def get_response(request):
            observed["correlation_id"] = get_correlation_id()
            response = MagicMock()
            response.__setitem__ = MagicMock()
            return response

        middleware = RequestIdMiddleware(get_response)
        request = RequestFactory().get("/health/")

        assert get_correlation_id() is None
        middleware(request)

        assert observed["correlation_id"] == request.request_id
        assert get_correlation_id() is None


@pytest.mark.django_db
class TestStructuredLoggingMiddleware:
    def test_logs_one_structured_line_per_request(self, api_client, caplog):
        with caplog.at_level(logging.INFO, logger="supportpilot"):
            api_client.get("/health/")

        records = [r for r in caplog.records if r.name == "supportpilot"]
        assert len(records) == 1
        record = records[0]
        assert record.method == "GET"
        assert record.path == "/health/"
        assert record.status == 200
        assert isinstance(record.elapsed_ms, int)
        assert record.request_id is not None
