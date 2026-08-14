"""Tests for the liveness/readiness health endpoints."""

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.mark.django_db
class TestHealthCheckView:
    def test_health_endpoint_returns_200_without_authentication(self, api_client):
        response = api_client.get("/health/")

        assert response.status_code == 200
        assert response.data == {"status": "healthy"}

    def test_health_endpoint_does_not_touch_the_database(self, api_client):
        with patch("django.db.connections") as mock_connections:
            response = api_client.get("/health/")

        assert response.status_code == 200
        mock_connections.__getitem__.assert_not_called()


@pytest.mark.django_db
class TestReadinessView:
    def test_readiness_endpoint_returns_200_when_database_is_reachable(self, api_client):
        response = api_client.get("/ready/")

        assert response.status_code == 200
        assert response.data == {"status": "ready"}

    def test_readiness_endpoint_returns_503_when_database_is_unreachable(self, api_client):
        with patch("health.views.connections") as mock_connections:
            mock_connections.__getitem__.return_value.ensure_connection.side_effect = Exception(
                "connection refused"
            )
            response = api_client.get("/ready/")

        assert response.status_code == 503
        assert response.data["status"] == "not_ready"

    def test_readiness_failure_does_not_leak_raw_exception_details(self, api_client):
        secret = "password authentication failed for user postgres"
        with patch("health.views.connections") as mock_connections:
            mock_connections.__getitem__.return_value.ensure_connection.side_effect = Exception(
                secret
            )
            response = api_client.get("/ready/")

        assert response.status_code == 503
        assert secret not in str(response.data)
        assert response.data == {"status": "not_ready"}
