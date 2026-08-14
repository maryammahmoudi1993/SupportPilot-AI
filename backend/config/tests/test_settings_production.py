"""Verifies the production-only security hardening block actually activates.

Reloads the settings *module* in isolation (not Django's global
`django.conf.settings`) with DEBUG=False so the `if not DEBUG:` branch runs,
without disturbing the settings the rest of the test suite depends on.
"""

import importlib

from config import settings as settings_module


class TestProductionSecurityHardening:
    def test_security_flags_enabled_when_debug_is_false(self, monkeypatch):
        monkeypatch.setenv("DEBUG", "False")
        monkeypatch.setenv("SECRET_KEY", "reload-test-secret")
        monkeypatch.setenv("DATABASE_URL", "postgres://u:p@localhost:5432/db")

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
