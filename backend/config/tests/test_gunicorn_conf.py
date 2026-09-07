"""Unit-level exercise of the Gunicorn multiprocess-metrics hooks (Phase 11
Block 1, section 29, 62). A real end-to-end proof that a live Gunicorn
process tree behaves correctly belongs to the production Docker smoke
(Block 6) — this only proves the two hook functions themselves are callable
and do what they claim against a fake server/worker, the same way
``config/asgi.py``/``config/wsgi.py`` are otherwise only exercised for real
in production, not via unit tests.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from config import gunicorn_conf


class TestOnStarting:
    def test_creates_a_fresh_multiproc_dir_and_sets_the_env_var(self, tmp_path, monkeypatch):
        target_dir = tmp_path / "prom-multiproc"
        # Pre-populate with a stale file from a hypothetical prior run to
        # prove it gets wiped, not merely created if absent.
        target_dir.mkdir()
        (target_dir / "stale.db").write_text("stale")
        monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(target_dir))

        gunicorn_conf.on_starting(server=MagicMock())

        assert os.environ["PROMETHEUS_MULTIPROC_DIR"] == str(target_dir)
        assert target_dir.is_dir()
        assert not (target_dir / "stale.db").exists()

    def test_falls_back_to_the_default_dir_when_env_var_absent(self, monkeypatch):
        monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)

        try:
            with patch("os.makedirs") as mock_makedirs, patch("shutil.rmtree"):
                gunicorn_conf.on_starting(server=MagicMock())

            mock_makedirs.assert_called_once_with(
                gunicorn_conf._DEFAULT_MULTIPROC_DIR, exist_ok=True
            )
            assert os.environ["PROMETHEUS_MULTIPROC_DIR"] == gunicorn_conf._DEFAULT_MULTIPROC_DIR
        finally:
            # ``on_starting`` writes directly to ``os.environ`` (by design —
            # forked Gunicorn workers must inherit it), which bypasses
            # monkeypatch's own undo tracking; restore it explicitly so this
            # test cannot leak process-global state into later tests.
            os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)


class TestChildExit:
    def test_marks_the_exited_worker_process_dead(self):
        worker = MagicMock(pid=12345)

        with patch("prometheus_client.multiprocess.mark_process_dead") as mock_mark:
            gunicorn_conf.child_exit(server=MagicMock(), worker=worker)

        mock_mark.assert_called_once_with(12345)


class TestConfigurableWorkerSettings:
    """Phase 17: worker count/timeouts read from environment at import time
    with conservative, documented defaults — never a workstation/build-host
    CPU-derived count (section 39)."""

    def test_defaults_are_conservative(self):
        assert gunicorn_conf.workers == 3
        assert gunicorn_conf.timeout == 30
        assert gunicorn_conf.graceful_timeout == 30
        assert gunicorn_conf.keepalive == 5

    def test_logs_go_to_stdout_and_stderr(self):
        assert gunicorn_conf.accesslog == "-"
        assert gunicorn_conf.errorlog == "-"

    def test_worker_count_is_overridable_via_environment(self, monkeypatch):
        monkeypatch.setenv("WEB_CONCURRENCY", "7")
        monkeypatch.setenv("WEB_TIMEOUT_SECONDS", "60")
        monkeypatch.setenv("WEB_GRACEFUL_TIMEOUT_SECONDS", "45")
        monkeypatch.setenv("WEB_KEEPALIVE_SECONDS", "2")

        import importlib

        reloaded = importlib.reload(gunicorn_conf)
        try:
            assert reloaded.workers == 7
            assert reloaded.timeout == 60
            assert reloaded.graceful_timeout == 45
            assert reloaded.keepalive == 2
        finally:
            # Restore module-level state for any test that runs after this
            # one and imports the same already-loaded module object.
            importlib.reload(gunicorn_conf)
