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


class TestSecretKeyProductionFailClosed:
    """Phase 17 Chunk 3/4 (PHASE17-C3-01): outside DEBUG, a missing/blank
    SECRET_KEY previously fell back silently to the publicly-known
    "dev-key-change-in-production" placeholder instead of refusing to boot.
    Locks the fix in place the same way TestObservabilityMetricsTokenFailClosed
    locks its sibling fail-fast check above."""

    def _reload_with(self, monkeypatch, **env_updates):
        for key, value in env_updates.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        return importlib.reload(settings_module)

    def test_missing_outside_debug_raises(self, monkeypatch):
        # django-environ's Env() default applies only when the var is truly
        # absent from the environment, so deleting it (rather than setting
        # "") exercises the actual "missing" case.
        monkeypatch.setenv("DEBUG", "False")
        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgres://u:p@localhost:5432/db")
        monkeypatch.setenv("OBSERVABILITY_METRICS_TOKEN", "reload-test-metrics-token")

        try:
            with pytest.raises(ValueError, match="SECRET_KEY"):
                importlib.reload(settings_module)
        finally:
            monkeypatch.undo()
            importlib.reload(settings_module)

    def test_blank_outside_debug_raises(self, monkeypatch):
        monkeypatch.setenv("DEBUG", "False")
        monkeypatch.setenv("SECRET_KEY", "")
        monkeypatch.setenv("DATABASE_URL", "postgres://u:p@localhost:5432/db")
        monkeypatch.setenv("OBSERVABILITY_METRICS_TOKEN", "reload-test-metrics-token")

        try:
            with pytest.raises(ValueError, match="SECRET_KEY"):
                importlib.reload(settings_module)
        finally:
            monkeypatch.undo()
            importlib.reload(settings_module)

    def test_dev_default_outside_debug_raises(self, monkeypatch):
        monkeypatch.setenv("DEBUG", "False")
        monkeypatch.setenv("SECRET_KEY", "dev-key-change-in-production")
        monkeypatch.setenv("DATABASE_URL", "postgres://u:p@localhost:5432/db")
        monkeypatch.setenv("OBSERVABILITY_METRICS_TOKEN", "reload-test-metrics-token")

        try:
            with pytest.raises(ValueError, match="SECRET_KEY"):
                importlib.reload(settings_module)
        finally:
            monkeypatch.undo()
            importlib.reload(settings_module)

    def test_strong_value_outside_debug_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("DEBUG", "False")
        monkeypatch.setenv("SECRET_KEY", "a-real-unique-production-secret-value")
        monkeypatch.setenv("DATABASE_URL", "postgres://u:p@localhost:5432/db")
        monkeypatch.setenv("OBSERVABILITY_METRICS_TOKEN", "reload-test-metrics-token")
        monkeypatch.delenv("SECURE_SSL_REDIRECT", raising=False)

        try:
            reloaded = importlib.reload(settings_module)
            assert reloaded.SECRET_KEY == "a-real-unique-production-secret-value"
        finally:
            monkeypatch.undo()
            importlib.reload(settings_module)

    def test_dev_default_inside_debug_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("DEBUG", "True")
        monkeypatch.delenv("SECRET_KEY", raising=False)

        try:
            reloaded = importlib.reload(settings_module)
            assert reloaded.DEBUG is True
            assert reloaded.SECRET_KEY == "dev-key-change-in-production"
        finally:
            monkeypatch.undo()
            importlib.reload(settings_module)
