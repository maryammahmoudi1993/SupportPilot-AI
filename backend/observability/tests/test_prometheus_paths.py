"""Phase 11 Block 5 (sections 23-24): path-safety guard for the two places
this codebase recursively deletes a directory tree
(``config/gunicorn_conf.py::on_starting`` and
``config/celery_metrics.py::_setup_multiproc_dir``), plus regression tests
proving both call sites actually invoke the guard before ``rmtree``."""

from __future__ import annotations

import sys

import pytest

from observability.prometheus_paths import (
    UnsafeMultiprocessDirError,
    assert_safe_multiprocess_dir,
    is_safe_multiprocess_dir,
)

#: Dangerous paths that are shallow/root on every platform this codebase
#: runs on. Windows drive-root cases ("C:\\", "C:\\Temp") are meaningless
#: path strings on POSIX — backslash isn't a path separator there, so they
#: resolve to an arbitrary relative segment under cwd rather than any real
#: filesystem root, and asserting they're "unsafe" on Linux would test a
#: string a Linux deployment could never actually be configured with. Each
#: platform's dangerous-path cases are therefore evaluated only under that
#: platform's own path semantics.
_POSIX_DANGEROUS_PATHS = ["/", "/tmp", ""]
_WINDOWS_DANGEROUS_PATHS = ["C:\\", "C:\\Temp", ""]
_DANGEROUS_PATHS = _WINDOWS_DANGEROUS_PATHS if sys.platform == "win32" else _POSIX_DANGEROUS_PATHS


class TestIsSafeMultiprocessDir:
    @pytest.mark.parametrize("dangerous_path", _DANGEROUS_PATHS)
    def test_rejects_shallow_or_root_paths(self, dangerous_path):
        assert is_safe_multiprocess_dir(dangerous_path) is False

    def test_rejects_the_home_directory(self):
        from pathlib import Path

        assert is_safe_multiprocess_dir(str(Path.home())) is False

    def test_rejects_the_repository_checkout_root(self):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent.parent
        assert is_safe_multiprocess_dir(str(repo_root)) is False

    def test_accepts_a_sufficiently_nested_dedicated_path(self, tmp_path):
        candidate = tmp_path / "supportpilot-prometheus-multiproc"
        assert is_safe_multiprocess_dir(str(candidate)) is True

    def test_accepts_the_shipped_default_paths(self):
        assert is_safe_multiprocess_dir("/tmp/supportpilot-prometheus-multiproc") is True
        assert is_safe_multiprocess_dir("/tmp/supportpilot-celery-prometheus-multiproc") is True

    def test_never_raises_on_a_path_it_cannot_resolve(self):
        assert is_safe_multiprocess_dir("\x00bad") is False


class TestAssertSafeMultiprocessDir:
    def test_safe_path_returns_the_resolved_path(self, tmp_path):
        candidate = tmp_path / "multiproc"
        result = assert_safe_multiprocess_dir(str(candidate))
        assert str(result) == str(candidate.resolve())

    def test_unsafe_path_raises(self):
        with pytest.raises(UnsafeMultiprocessDirError):
            assert_safe_multiprocess_dir("/")


class TestGunicornConfWiring:
    """Regression: ``on_starting`` must refuse an unsafe directory *before*
    ever calling ``shutil.rmtree`` — never after, never conditionally."""

    def test_unsafe_dir_raises_and_never_calls_rmtree(self, monkeypatch):
        import config.gunicorn_conf as gunicorn_conf

        monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", "/")
        rmtree_calls = []
        monkeypatch.setattr(
            gunicorn_conf.shutil, "rmtree", lambda *a, **k: rmtree_calls.append((a, k))
        )

        with pytest.raises(Exception):  # noqa: B017 - any exception must stop before rmtree
            gunicorn_conf.on_starting(server=None)

        assert rmtree_calls == []

    def test_safe_dir_proceeds_normally(self, monkeypatch, tmp_path):
        import config.gunicorn_conf as gunicorn_conf

        target = tmp_path / "gunicorn-multiproc"
        monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(target))

        gunicorn_conf.on_starting(server=None)

        assert target.is_dir()
        import os

        assert os.environ["PROMETHEUS_MULTIPROC_DIR"] == str(target)


class TestCeleryMetricsDirWiring:
    def test_unsafe_dir_raises_and_never_calls_rmtree(self, monkeypatch, settings):
        import config.celery_metrics as celery_metrics

        settings.OBSERVABILITY_CELERY_PROMETHEUS_MULTIPROC_DIR = "/"
        rmtree_calls = []
        monkeypatch.setattr(
            celery_metrics.shutil, "rmtree", lambda *a, **k: rmtree_calls.append((a, k))
        )

        with pytest.raises(Exception):  # noqa: B017
            celery_metrics._setup_multiproc_dir()

        assert rmtree_calls == []

    def test_setup_multiproc_dir_if_worker_process_fails_open_when_the_configured_dir_is_unsafe(
        self, settings, caplog, monkeypatch
    ):
        """The directory/env-var setup (moved to
        ``setup_multiproc_dir_if_worker_process``, called at
        ``config/celery.py`` import time — see that function's docstring for
        why it can no longer live in ``on_worker_init``) still wraps
        ``_setup_multiproc_dir`` in a broad fail-open ``try/except``: a
        broken exposition setup must never prevent the worker from starting.
        An unsafe directory degrades to "no exposition this worker", never a
        crash and never a ``rmtree``."""
        import logging
        import sys

        import config.celery_metrics as celery_metrics

        monkeypatch.setattr(
            sys, "argv", ["/usr/local/bin/celery", "-A", "config", "worker", "--loglevel=info"]
        )
        settings.OBSERVABILITY_CELERY_METRICS_ENABLED = True
        settings.OBSERVABILITY_CELERY_PROMETHEUS_MULTIPROC_DIR = "/"

        with caplog.at_level(logging.WARNING):
            celery_metrics.setup_multiproc_dir_if_worker_process()  # hard gate: must not raise

        assert any("celery_metrics_init_failed" in r.getMessage() for r in caplog.records)

    def test_on_worker_init_no_longer_touches_the_multiproc_dir(self, settings, caplog):
        """Regression: ``on_worker_init`` must not itself attempt the
        directory setup any more — doing so would run *after* Celery's own
        task-module autodiscovery has already imported
        ``observability.metrics`` (see
        ``setup_multiproc_dir_if_worker_process``'s docstring), too late to
        matter. An unsafe configured directory must therefore never surface
        through ``on_worker_init`` at all, safe or not."""
        import logging

        import config.celery_metrics as celery_metrics

        settings.OBSERVABILITY_CELERY_METRICS_ENABLED = True
        settings.OBSERVABILITY_CELERY_PROMETHEUS_MULTIPROC_DIR = "/"
        celery_metrics.reset_for_tests()

        try:
            with caplog.at_level(logging.WARNING):
                celery_metrics.on_worker_init()  # hard gate: must not raise

            assert not any("celery_metrics_init_failed" in r.getMessage() for r in caplog.records)
        finally:
            celery_metrics.reset_for_tests()

    def test_safe_dir_proceeds_normally(self, settings, tmp_path):
        import config.celery_metrics as celery_metrics

        target = tmp_path / "celery-multiproc"
        settings.OBSERVABILITY_CELERY_PROMETHEUS_MULTIPROC_DIR = str(target)

        celery_metrics._setup_multiproc_dir()

        assert target.is_dir()
        import os

        assert os.environ["PROMETHEUS_MULTIPROC_DIR"] == str(target)
