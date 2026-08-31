"""Metrics endpoint auth/content-safety tests (Phase 11 Block 1, sections
27-28, 48)."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

METRICS_TOKEN = "test-metrics-token-abc123"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.mark.django_db
class TestMetricsEndpointAuth:
    def test_missing_authorization_header_is_denied(self, api_client, settings):
        settings.OBSERVABILITY_METRICS_ENABLED = True
        settings.OBSERVABILITY_METRICS_TOKEN = METRICS_TOKEN

        response = api_client.get("/metrics/")

        assert response.status_code == 404

    def test_wrong_token_is_denied(self, api_client, settings):
        settings.OBSERVABILITY_METRICS_ENABLED = True
        settings.OBSERVABILITY_METRICS_TOKEN = METRICS_TOKEN

        response = api_client.get("/metrics/", HTTP_AUTHORIZATION="Bearer wrong-token")

        assert response.status_code == 404

    def test_malformed_header_without_bearer_prefix_is_denied(self, api_client, settings):
        settings.OBSERVABILITY_METRICS_ENABLED = True
        settings.OBSERVABILITY_METRICS_TOKEN = METRICS_TOKEN

        response = api_client.get("/metrics/", HTTP_AUTHORIZATION=METRICS_TOKEN)

        assert response.status_code == 404

    def test_correct_token_is_accepted(self, api_client, settings):
        settings.OBSERVABILITY_METRICS_ENABLED = True
        settings.OBSERVABILITY_METRICS_TOKEN = METRICS_TOKEN

        response = api_client.get("/metrics/", HTTP_AUTHORIZATION=f"Bearer {METRICS_TOKEN}")

        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/plain")

    def test_disabled_denies_even_with_correct_token(self, api_client, settings):
        settings.OBSERVABILITY_METRICS_ENABLED = False
        settings.OBSERVABILITY_METRICS_TOKEN = METRICS_TOKEN

        response = api_client.get("/metrics/", HTTP_AUTHORIZATION=f"Bearer {METRICS_TOKEN}")

        assert response.status_code == 404

    def test_no_configured_token_denies_every_request(self, api_client, settings):
        settings.OBSERVABILITY_METRICS_ENABLED = True
        settings.OBSERVABILITY_METRICS_TOKEN = ""

        response = api_client.get("/metrics/", HTTP_AUTHORIZATION="Bearer anything")

        assert response.status_code == 404

    def test_disabled_and_enabled_denials_are_identical(self, api_client, settings):
        """Section 27: a denial must never leak *why* it was denied."""
        settings.OBSERVABILITY_METRICS_ENABLED = True
        settings.OBSERVABILITY_METRICS_TOKEN = METRICS_TOKEN
        wrong_token_response = api_client.get("/metrics/", HTTP_AUTHORIZATION="Bearer wrong")

        settings.OBSERVABILITY_METRICS_ENABLED = False
        disabled_response = api_client.get("/metrics/", HTTP_AUTHORIZATION="Bearer wrong")

        assert wrong_token_response.status_code == disabled_response.status_code == 404
        assert wrong_token_response.content == disabled_response.content


@pytest.mark.django_db
class TestMetricsEndpointContentSafety:
    def test_authenticated_scrape_never_leaks_the_bearer_token_itself(self, api_client, settings):
        settings.OBSERVABILITY_METRICS_ENABLED = True
        settings.OBSERVABILITY_METRICS_TOKEN = METRICS_TOKEN

        response = api_client.get("/metrics/", HTTP_AUTHORIZATION=f"Bearer {METRICS_TOKEN}")

        assert METRICS_TOKEN not in response.content.decode("utf-8")

    def test_scrape_output_contains_no_workspace_or_request_identifiers(self, api_client, settings):
        settings.OBSERVABILITY_METRICS_ENABLED = True
        settings.OBSERVABILITY_METRICS_TOKEN = METRICS_TOKEN

        # Generate some request traffic carrying a marker value first.
        api_client.get("/api/v1/does-not-exist/", HTTP_X_REQUEST_ID="SUPER_SECRET_MARKER_918273")

        response = api_client.get("/metrics/", HTTP_AUTHORIZATION=f"Bearer {METRICS_TOKEN}")
        body = response.content.decode("utf-8")

        assert "SUPER_SECRET_MARKER_918273" not in body
