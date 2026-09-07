"""Celery Beat registration (Phase 10 Block 4, section 17-19): the recovery
sweeper tasks are registered, carry no domain logic themselves (delegated
entirely to ``notifications.recovery`` — see ``notifications/tasks.py``), and
run on a coarse, non-sub-second cadence (section 18)."""

from __future__ import annotations

from config.celery import app


def test_recovery_sweeper_tasks_are_registered_in_beat_schedule():
    schedule = app.conf.beat_schedule
    assert schedule["dispatch-due-deliveries"]["task"] == (
        "notifications.tasks.dispatch_due_deliveries_task"
    )
    assert schedule["recover-expired-delivery-claims"]["task"] == (
        "notifications.tasks.recover_expired_delivery_claims_task"
    )


def test_recovery_sweeper_schedule_is_not_sub_second():
    schedule = app.conf.beat_schedule
    assert schedule["dispatch-due-deliveries"]["schedule"] >= 1.0
    assert schedule["recover-expired-delivery-claims"]["schedule"] >= 1.0


def test_recovery_sweeper_schedule_matches_the_configured_interval_setting(settings):
    """The beat schedule built at import time reflects
    ``settings.DELIVERY_SWEEP_INTERVAL_SECONDS`` (section 18: server-owned
    *and* configurable, not merely a hardcoded server-owned number) —
    reflects it, rather than only asserting a fixed literal, so changing the
    setting is what actually changes the cadence."""
    schedule = app.conf.beat_schedule
    assert schedule["dispatch-due-deliveries"]["schedule"] == float(
        settings.DELIVERY_SWEEP_INTERVAL_SECONDS
    )
    assert schedule["recover-expired-delivery-claims"]["schedule"] == float(
        settings.DELIVERY_SWEEP_INTERVAL_SECONDS
    )


def test_delivery_sweep_interval_helper_reads_the_setting_live(settings):
    """The builder used to construct the schedule is a genuine settings
    read, not a value frozen once at process start — proven by overriding
    the setting and calling it again."""
    from config.celery import _delivery_sweep_interval_seconds

    settings.DELIVERY_SWEEP_INTERVAL_SECONDS = 45
    assert _delivery_sweep_interval_seconds() == 45.0

    settings.DELIVERY_SWEEP_INTERVAL_SECONDS = 90
    assert _delivery_sweep_interval_seconds() == 90.0


def test_recovery_sweeper_tasks_are_importable_and_registered_with_celery():
    from notifications.tasks import (
        dispatch_due_deliveries_task,
        recover_expired_delivery_claims_task,
    )

    assert dispatch_due_deliveries_task.name == "notifications.tasks.dispatch_due_deliveries_task"
    assert (
        recover_expired_delivery_claims_task.name
        == "notifications.tasks.recover_expired_delivery_claims_task"
    )


# ---------------------------------------------------------------------------
# Stuck-worker recovery sweepers (Phase 17): AgentRun/EvaluationRun recovery
# logic was built in Phase 16 (agents/recovery.py, evaluations/recovery.py)
# but deliberately left unscheduled — this closes that packaging gap.
# ---------------------------------------------------------------------------


def test_stuck_run_recovery_tasks_are_registered_in_beat_schedule():
    schedule = app.conf.beat_schedule
    assert (
        schedule["recover-stuck-agent-runs"]["task"] == "agents.tasks.recover_stuck_agent_runs_task"
    )
    assert (
        schedule["recover-stuck-evaluation-runs"]["task"]
        == "evaluations.tasks.recover_stuck_evaluation_runs_task"
    )


def test_stuck_run_recovery_schedule_is_not_sub_second():
    schedule = app.conf.beat_schedule
    assert schedule["recover-stuck-agent-runs"]["schedule"] >= 1.0
    assert schedule["recover-stuck-evaluation-runs"]["schedule"] >= 1.0


def test_stuck_run_recovery_schedule_matches_the_configured_interval_setting(settings):
    schedule = app.conf.beat_schedule
    assert schedule["recover-stuck-agent-runs"]["schedule"] == float(
        settings.AGENTS_STUCK_RUN_SWEEP_INTERVAL_SECONDS
    )
    assert schedule["recover-stuck-evaluation-runs"]["schedule"] == float(
        settings.EVALUATIONS_STUCK_RUN_SWEEP_INTERVAL_SECONDS
    )


def test_stuck_run_sweep_interval_helpers_read_the_setting_live(settings):
    from config.celery import (
        _agents_stuck_run_sweep_interval_seconds,
        _evaluations_stuck_run_sweep_interval_seconds,
    )

    settings.AGENTS_STUCK_RUN_SWEEP_INTERVAL_SECONDS = 45
    assert _agents_stuck_run_sweep_interval_seconds() == 45.0
    settings.AGENTS_STUCK_RUN_SWEEP_INTERVAL_SECONDS = 90
    assert _agents_stuck_run_sweep_interval_seconds() == 90.0

    settings.EVALUATIONS_STUCK_RUN_SWEEP_INTERVAL_SECONDS = 45
    assert _evaluations_stuck_run_sweep_interval_seconds() == 45.0
    settings.EVALUATIONS_STUCK_RUN_SWEEP_INTERVAL_SECONDS = 90
    assert _evaluations_stuck_run_sweep_interval_seconds() == 90.0


def test_stuck_run_recovery_tasks_are_importable_and_registered_with_celery():
    from agents.tasks import recover_stuck_agent_runs_task
    from evaluations.tasks import recover_stuck_evaluation_runs_task

    assert recover_stuck_agent_runs_task.name == "agents.tasks.recover_stuck_agent_runs_task"
    assert (
        recover_stuck_evaluation_runs_task.name
        == "evaluations.tasks.recover_stuck_evaluation_runs_task"
    )


# ---------------------------------------------------------------------------
# Stuck knowledge-ingestion-job recovery (Phase 17 final acceptance gate,
# Part B): closes the one gap the task-durability inventory found —
# KnowledgeIngestionJob had a durable row but no periodic recovery path.
# ---------------------------------------------------------------------------


def test_stuck_knowledge_job_recovery_task_is_registered_in_beat_schedule():
    schedule = app.conf.beat_schedule
    assert (
        schedule["recover-stuck-knowledge-ingestion-jobs"]["task"]
        == "knowledge.tasks.recover_stuck_ingestion_jobs_task"
    )


def test_stuck_knowledge_job_recovery_schedule_is_not_sub_second():
    schedule = app.conf.beat_schedule
    assert schedule["recover-stuck-knowledge-ingestion-jobs"]["schedule"] >= 1.0


def test_stuck_knowledge_job_recovery_schedule_matches_the_configured_interval_setting(settings):
    schedule = app.conf.beat_schedule
    assert schedule["recover-stuck-knowledge-ingestion-jobs"]["schedule"] == float(
        settings.KNOWLEDGE_STUCK_JOB_SWEEP_INTERVAL_SECONDS
    )


def test_knowledge_stuck_job_sweep_interval_helper_reads_the_setting_live(settings):
    from config.celery import _knowledge_stuck_job_sweep_interval_seconds

    settings.KNOWLEDGE_STUCK_JOB_SWEEP_INTERVAL_SECONDS = 45
    assert _knowledge_stuck_job_sweep_interval_seconds() == 45.0
    settings.KNOWLEDGE_STUCK_JOB_SWEEP_INTERVAL_SECONDS = 90
    assert _knowledge_stuck_job_sweep_interval_seconds() == 90.0


def test_stuck_knowledge_job_recovery_task_is_importable_and_registered_with_celery():
    from knowledge.tasks import recover_stuck_ingestion_jobs_task

    assert (
        recover_stuck_ingestion_jobs_task.name
        == "knowledge.tasks.recover_stuck_ingestion_jobs_task"
    )


# ---------------------------------------------------------------------------
# Structural consistency (Phase 17 final acceptance gate, section 12): no
# Beat schedule entry may reference a task Celery doesn't actually know
# about (missing/renamed/unregistered) — checked against the app's own
# registered-task names, never against the schedule's own text.
# ---------------------------------------------------------------------------


def test_every_beat_schedule_task_is_registered_with_celery():
    """``app.tasks`` only actually contains a first-party task once its
    module has been imported somewhere in this process — true in a real
    ``celery worker``/``celery beat`` process (``app.autodiscover_tasks()``
    at import time in config/celery.py imports every app's ``tasks.py``),
    but not guaranteed under pytest unless something already imported it.
    Import every task module every schedule entry names first, so this
    check is deterministic regardless of which other test files ran in the
    same session/order."""
    import importlib

    for entry in app.conf.beat_schedule.values():
        module_path, _, _ = entry["task"].rpartition(".")
        importlib.import_module(module_path)

    registered = set(app.tasks.keys())
    for entry_name, entry in app.conf.beat_schedule.items():
        assert entry["task"] in registered, (
            f"beat_schedule entry {entry_name!r} references "
            f"{entry['task']!r}, which is not a registered Celery task"
        )
