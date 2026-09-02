"""SECURE_SSL_REDIRECT is decoupled from DEBUG via an explicit env override
(config/settings.py) — added after Phase 14 Milestone 5's final gate found
that ``backend-ci.yml``'s own ``DEBUG=False`` (with no TLS listener in a CI
runner) made Django's SecurityMiddleware redirect every plain-HTTP
test-client request to https, turning hundreds of real view-test passes
into a false ``301`` before their actual assertion ever ran.

These tests prove: (1) the production default is unchanged — outside
DEBUG, with no override, the redirect is still on; (2) an explicit
``SECURE_SSL_REDIRECT=False`` override — the one CI now sets — actually
disables it even outside DEBUG; (3) inside DEBUG the setting is never
forced either way, matching Django's own default.

Settings are only evaluated once at process start, so these run each case
in a fresh subprocess, the same pattern already used for DRF_NUM_PROXIES
parsing (see test_trusted_proxy_identity.py).
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

_CHILD_SCRIPT = textwrap.dedent("""
    import django
    django.setup()
    from django.conf import settings
    print("SECURE_SSL_REDIRECT=" + repr(getattr(settings, "SECURE_SSL_REDIRECT", None)))
    """)


def _run(*, debug: str, override: str | None) -> subprocess.CompletedProcess:
    backend_root = str(Path(__file__).resolve().parent.parent.parent)
    env = os.environ.copy()
    env["DEBUG"] = debug
    env.pop("SECURE_SSL_REDIRECT", None)
    if override is not None:
        env["SECURE_SSL_REDIRECT"] = override
    env.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    # Outside DEBUG, OBSERVABILITY_METRICS_ENABLED's own default (True)
    # requires a token — unrelated to what this test is checking, so set
    # it unconditionally rather than let every DEBUG=False case fail on it.
    env.setdefault("OBSERVABILITY_METRICS_TOKEN", "test-metrics-token")
    return subprocess.run(
        [sys.executable, "-c", _CHILD_SCRIPT],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=backend_root,
        env=env,
    )


class TestSecureSslRedirectConfig:
    def test_production_default_unchanged_when_unset(self):
        # Outside DEBUG, with no override: still redirects — the safe
        # production posture this repo has always had.
        result = _run(debug="False", override=None)
        assert result.returncode == 0, result.stderr
        assert "SECURE_SSL_REDIRECT=True" in result.stdout

    def test_explicit_false_override_disables_it_outside_debug(self):
        # What backend-ci.yml now sets: DEBUG=False (production-like) but
        # no TLS listener, so the redirect must be explicitly off.
        result = _run(debug="False", override="False")
        assert result.returncode == 0, result.stderr
        assert "SECURE_SSL_REDIRECT=False" in result.stdout

    def test_explicit_true_override_outside_debug_is_a_no_op(self):
        result = _run(debug="False", override="True")
        assert result.returncode == 0, result.stderr
        assert "SECURE_SSL_REDIRECT=True" in result.stdout

    def test_inside_debug_the_setting_is_never_forced(self):
        # DEBUG=True never enters the `if not DEBUG:` block at all —
        # SECURE_SSL_REDIRECT falls back to Django's own default (False),
        # regardless of any override, matching pre-existing local/dev
        # behavior.
        result = _run(debug="True", override=None)
        assert result.returncode == 0, result.stderr
        assert "SECURE_SSL_REDIRECT=False" in result.stdout
