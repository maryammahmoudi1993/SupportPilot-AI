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
