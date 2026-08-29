"""Tests for prefork-safe Celery metrics exposition (Phase 11 Block 3,
sections 4-7, 52 — a hard gate: worker-recorded metrics must be provably
visible through the parent exposition endpoint)."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import textwrap
import urllib.request
from unittest.mock import patch

from config import celery_metrics


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


class TestMultiprocDirLifecycle:
    def test_creates_a_fresh_directory_and_sets_the_env_var(self, tmp_path, settings):
        target_dir = tmp_path / "celery-prom-multiproc"
        target_dir.mkdir()
        (target_dir / "stale.db").write_text("stale")
        settings.OBSERVABILITY_CELERY_PROMETHEUS_MULTIPROC_DIR = str(target_dir)

        try:
            celery_metrics._setup_multiproc_dir()

            assert os.environ["PROMETHEUS_MULTIPROC_DIR"] == str(target_dir)
            assert target_dir.is_dir()
            assert not (target_dir / "stale.db").exists()
        finally:
            os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)

    def test_a_second_worker_master_start_does_not_contaminate_with_stale_files(
        self, tmp_path, settings
    ):
        target_dir = tmp_path / "celery-prom-multiproc"
        settings.OBSERVABILITY_CELERY_PROMETHEUS_MULTIPROC_DIR = str(target_dir)

        try:
            celery_metrics._setup_multiproc_dir()
            (target_dir / "worker-1-12345.db").write_text("old worker mmap data")

            celery_metrics._setup_multiproc_dir()  # simulates a second master start

            assert not (target_dir / "worker-1-12345.db").exists()
        finally:
            os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)


class TestOnWorkerInit:
    def test_disabled_by_default_touches_nothing(self, settings, tmp_path):
        settings.OBSERVABILITY_CELERY_METRICS_ENABLED = False
        settings.OBSERVABILITY_CELERY_PROMETHEUS_MULTIPROC_DIR = str(tmp_path / "unused")

        with patch.object(celery_metrics, "_setup_multiproc_dir") as mock_setup:
            with patch.object(celery_metrics, "_start_exposition_server") as mock_start:
                celery_metrics.on_worker_init()

        mock_setup.assert_not_called()
        mock_start.assert_not_called()

    def test_enabled_sets_up_directory_and_starts_the_server_exactly_once(self, settings, tmp_path):
        settings.OBSERVABILITY_CELERY_METRICS_ENABLED = True
        settings.OBSERVABILITY_CELERY_PROMETHEUS_MULTIPROC_DIR = str(tmp_path / "multiproc")
        settings.OBSERVABILITY_CELERY_METRICS_HOST = "127.0.0.1"
        settings.OBSERVABILITY_CELERY_METRICS_PORT = _free_port()
        celery_metrics.reset_for_tests()

        try:
            celery_metrics.on_worker_init()
            first_server = celery_metrics._server
            celery_metrics.on_worker_init()  # a second dispatch must not rebind the port

            assert first_server is celery_metrics._server
        finally:
            celery_metrics.reset_for_tests()
            os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)

    def test_init_failure_is_caught_worker_still_starts(self, settings, tmp_path):
        settings.OBSERVABILITY_CELERY_METRICS_ENABLED = True
        settings.OBSERVABILITY_CELERY_PROMETHEUS_MULTIPROC_DIR = str(tmp_path / "multiproc")

        with patch.object(
            celery_metrics, "_setup_multiproc_dir", side_effect=RuntimeError("disk full")
        ):
            celery_metrics.on_worker_init()  # must not raise


class TestChildProcessesNeverBindThePort:
    def test_no_child_side_signal_starts_a_server(self):
        """Section 4/7: prefork children must never independently bind the
        metrics port. There is deliberately no
        ``worker_process_init``-connected handler in this module at all —
        only ``worker_init`` (parent, pre-fork) starts the listener."""
        import celery.signals as signals

        receivers = [
            receiver
            for receiver in signals.worker_process_init.receivers
            if "celery_metrics" in repr(receiver)
        ]
        assert receivers == []


class TestWorkerProcessShutdown:
    def test_marks_the_exited_child_process_dead(self, settings):
        settings.OBSERVABILITY_CELERY_METRICS_ENABLED = True

        with patch("prometheus_client.multiprocess.mark_process_dead") as mock_mark:
            celery_metrics.on_worker_process_shutdown(pid=54321, exitcode=0)

        mock_mark.assert_called_once_with(54321)

    def test_disabled_does_not_call_mark_process_dead(self, settings):
        settings.OBSERVABILITY_CELERY_METRICS_ENABLED = False

        with patch("prometheus_client.multiprocess.mark_process_dead") as mock_mark:
            celery_metrics.on_worker_process_shutdown(pid=54321, exitcode=0)

        mock_mark.assert_not_called()

    def test_missing_pid_is_a_safe_no_op(self, settings):
        settings.OBSERVABILITY_CELERY_METRICS_ENABLED = True

        celery_metrics.on_worker_process_shutdown(pid=None, exitcode=0)  # must not raise

    def test_cleanup_failure_is_caught(self, settings):
        settings.OBSERVABILITY_CELERY_METRICS_ENABLED = True

        with patch(
            "prometheus_client.multiprocess.mark_process_dead",
            side_effect=RuntimeError("mmap gone"),
        ):
            celery_metrics.on_worker_process_shutdown(pid=1, exitcode=0)  # must not raise


class TestExpositionServerFailureIsolation:
    def test_a_port_already_in_use_does_not_raise(self, settings, tmp_path):
        port = _free_port()
        occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        occupied.bind(("127.0.0.1", port))
        occupied.listen(1)
        try:
            settings.OBSERVABILITY_CELERY_METRICS_HOST = "127.0.0.1"
            settings.OBSERVABILITY_CELERY_METRICS_PORT = port
            celery_metrics.reset_for_tests()

            celery_metrics._start_exposition_server()  # must not raise

            assert celery_metrics._server is None
        finally:
            occupied.close()
            celery_metrics.reset_for_tests()


class TestLiveScrapeIncludesRecordedMetrics:
    """A real end-to-end proof, not a mock: bind the actual listener and
    scrape it over a real HTTP connection."""

    def test_scrape_reflects_a_metric_recorded_before_the_server_started(self, settings):
        from observability.metrics import observe_celery_task

        observe_celery_task(
            task_name="test.celery_metrics.live_scrape", outcome="success", duration_seconds=0.01
        )

        settings.OBSERVABILITY_CELERY_METRICS_HOST = "127.0.0.1"
        settings.OBSERVABILITY_CELERY_METRICS_PORT = _free_port()
        celery_metrics.reset_for_tests()
        try:
            celery_metrics._start_exposition_server()
            assert celery_metrics._server is not None

            url = (
                f"http://{settings.OBSERVABILITY_CELERY_METRICS_HOST}:"
                f"{settings.OBSERVABILITY_CELERY_METRICS_PORT}/metrics"
            )
            with urllib.request.urlopen(url, timeout=5) as response:
                body = response.read().decode("utf-8")

            assert "supportpilot_celery_tasks_total" in body
            assert 'task_name="test.celery_metrics.live_scrape"' in body
        finally:
            celery_metrics.reset_for_tests()

    def test_unknown_path_returns_404(self, settings):
        settings.OBSERVABILITY_CELERY_METRICS_HOST = "127.0.0.1"
        settings.OBSERVABILITY_CELERY_METRICS_PORT = _free_port()
        celery_metrics.reset_for_tests()
        try:
            celery_metrics._start_exposition_server()

            url = (
                f"http://{settings.OBSERVABILITY_CELERY_METRICS_HOST}:"
                f"{settings.OBSERVABILITY_CELERY_METRICS_PORT}/not-metrics"
            )
            try:
                urllib.request.urlopen(url, timeout=5)
                raised = False
            except Exception as exc:  # noqa: BLE001
                raised = True
                assert "404" in str(exc)
            assert raised
        finally:
            celery_metrics.reset_for_tests()


class TestCrossProcessMultiprocessScrape:
    """The genuine multiprocess-file proof (section 52's hard gate): a
    *separate real OS process* — standing in for a prefork child — records
    a metric with ``PROMETHEUS_MULTIPROC_DIR`` set before it ever imports
    ``observability.metrics`` (required for the mmap-backed value class to
    be selected, per that module's own docstring). The parent process (this
    test) then aggregates purely from the on-disk mmap files the child
    process left behind, exactly as ``render_metrics()`` does for a real
    scrape — proving a prefork child's metrics are actually visible through
    the shared multiprocess directory, independent of any in-memory state
    this test process itself holds."""

    def test_child_process_metric_is_visible_via_multiprocess_collector(self, tmp_path):
        multiproc_dir = tmp_path / "cross-process-multiproc"
        multiproc_dir.mkdir()

        backend_root = str(__import__("pathlib").Path(__file__).parent.parent.parent)
        child_script = textwrap.dedent(f"""
            import os
            os.environ["PROMETHEUS_MULTIPROC_DIR"] = {str(multiproc_dir)!r}
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
            import sys
            sys.path.insert(0, {backend_root!r})
            import django
            django.setup()
            from observability.metrics import observe_celery_task
            observe_celery_task(
                task_name="test.cross_process.child_task",
                outcome="success",
                duration_seconds=0.02,
            )
            """)
        result = subprocess.run(
            [sys.executable, "-c", child_script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr

        from prometheus_client import CollectorRegistry, generate_latest, multiprocess

        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry, path=str(multiproc_dir))
        body = generate_latest(registry).decode("utf-8")

        assert "supportpilot_celery_tasks_total" in body
        assert 'task_name="test.cross_process.child_task"' in body
