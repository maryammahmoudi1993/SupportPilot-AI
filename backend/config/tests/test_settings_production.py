"""Verifies the production-only security hardening block actually activates.

Reloads the settings *module* in isolation (not Django's global
`django.conf.settings`) with DEBUG=False so the `if not DEBUG:` branch runs,
without disturbing the settings the rest of the test suite depends on.
"""

import importlib

import pytest

from config import settings as settings_module


class TestProductionSecurityHardening:
    def test_security_flags_enabled_when_debug_is_false(self, monkeypatch):
        monkeypatch.setenv("DEBUG", "False")
        monkeypatch.setenv("SECRET_KEY", "reload-test-secret")
        monkeypatch.setenv("DATABASE_URL", "postgres://u:p@localhost:5432/db")
        # Phase 11 Block 1: production (DEBUG=False) settings now fail fast
        # if metrics are enabled without a token (see
        # TestObservabilityMetricsTokenFailClosed below) — this test is
        # about the unrelated security-header hardening block, so it must
        # supply a token to keep reaching that code.
        monkeypatch.setenv("OBSERVABILITY_METRICS_TOKEN", "reload-test-metrics-token")
        # This test verifies the *unset* SECURE_SSL_REDIRECT default (True
        # outside DEBUG) — Phase 14 Milestone 5 made it an explicit,
        # overridable env var (e.g. CI legitimately sets it to False, since
        # a CI runner has no TLS listener); clear any inherited value from
        # the calling environment so this test always exercises the real
        # default, not whatever happens to be set around it.
        monkeypatch.delenv("SECURE_SSL_REDIRECT", raising=False)

        try:
            reloaded = importlib.reload(settings_module)

            assert reloaded.DEBUG is False
            assert reloaded.SECURE_SSL_REDIRECT is True
            assert reloaded.SESSION_COOKIE_SECURE is True
            assert reloaded.CSRF_COOKIE_SECURE is True
            assert reloaded.SECURE_HSTS_SECONDS == 31536000
            assert reloaded.SECURE_HSTS_INCLUDE_SUBDOMAINS is True
            assert reloaded.SECURE_HSTS_PRELOAD is True
        finally:
            # Restore the module the rest of the suite (and Django's app
            # registry) expects to be running under DEBUG=True test settings.
            monkeypatch.undo()
            importlib.reload(settings_module)


class TestObservabilityMetricsTokenFailClosed:
    """Phase 11 Block 1 (section 26-27): an unauthenticated metrics endpoint
    reachable in a real deployment is a release blocker, so a production
    (DEBUG=False) boot with metrics enabled and no token configured must
    fail fast at settings-import time rather than silently exposing an
    endpoint nothing can deny requests from."""

    def test_enabled_without_token_outside_debug_raises(self, monkeypatch):
        monkeypatch.setenv("DEBUG", "False")
        monkeypatch.setenv("SECRET_KEY", "reload-test-secret")
        monkeypatch.setenv("DATABASE_URL", "postgres://u:p@localhost:5432/db")
        monkeypatch.setenv("OBSERVABILITY_METRICS_ENABLED", "True")
        monkeypatch.setenv("OBSERVABILITY_METRICS_TOKEN", "")

        try:
            with pytest.raises(ValueError, match="OBSERVABILITY_METRICS_TOKEN"):
                importlib.reload(settings_module)
        finally:
            monkeypatch.undo()
            importlib.reload(settings_module)

    def test_enabled_with_token_outside_debug_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("DEBUG", "False")
        monkeypatch.setenv("SECRET_KEY", "reload-test-secret")
        monkeypatch.setenv("DATABASE_URL", "postgres://u:p@localhost:5432/db")
        monkeypatch.setenv("OBSERVABILITY_METRICS_ENABLED", "True")
        monkeypatch.setenv("OBSERVABILITY_METRICS_TOKEN", "a-real-token")

        try:
            reloaded = importlib.reload(settings_module)
            assert reloaded.OBSERVABILITY_METRICS_TOKEN == "a-real-token"
        finally:
            monkeypatch.undo()
            importlib.reload(settings_module)

    def test_disabled_without_token_outside_debug_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("DEBUG", "False")
        monkeypatch.setenv("SECRET_KEY", "reload-test-secret")
        monkeypatch.setenv("DATABASE_URL", "postgres://u:p@localhost:5432/db")
        monkeypatch.setenv("OBSERVABILITY_METRICS_ENABLED", "False")
        monkeypatch.setenv("OBSERVABILITY_METRICS_TOKEN", "")

        try:
            reloaded = importlib.reload(settings_module)
            assert reloaded.OBSERVABILITY_METRICS_ENABLED is False
        finally:
            monkeypatch.undo()
            importlib.reload(settings_module)

    def test_enabled_without_token_inside_debug_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("DEBUG", "True")
        monkeypatch.setenv("OBSERVABILITY_METRICS_ENABLED", "True")
        monkeypatch.setenv("OBSERVABILITY_METRICS_TOKEN", "")

        try:
            reloaded = importlib.reload(settings_module)
            assert reloaded.DEBUG is True
        finally:
            monkeypatch.undo()
            importlib.reload(settings_module)
