"""Notification-specific delivery tests (Phase 10 Block 2, section 29):
creation/idempotency, the frozen recipient/content snapshot, fake-provider
success and failure classification, max-attempt bounds, stale-claim
protection inherited from Block 1, and secret safety.

Uses the deterministic ``FakeNotificationProvider`` (Phase 7) exactly as the
existing tool-level tests do — never a live/network provider.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from django.utils import timezone

from integrations.errors import (
    IntegrationAuthenticationFailedError,
    IntegrationConfigurationError,
    IntegrationInvalidRequestError,
    IntegrationRateLimitedError,
    IntegrationTemporarilyUnavailableError,
    IntegrationTimeoutError,
)
from integrations.models import IntegrationProvider
from integrations.providers.fakes import FakeNotificationProvider
from integrations.tests.factories import IntegrationConnectionFactory
from notifications.errors import DeliveryNotClaimableError, StaleClaimError
from notifications.models import (
    AttemptStatus,
    DeliveryAttempt,
    DeliveryChannel,
    DeliveryStatus,
    NotificationDelivery,
    NotificationMedium,
)
from notifications.notification_delivery import (
    MISSING_SNAPSHOT_ERROR_CODE,
    UNEXPECTED_ERROR_CODE,
    create_or_reuse_notification_delivery,
    handle_notification_delivery_attempt,
)
from notifications.services import (
    claim_delivery,
    create_delivery,
    process_claimed_delivery,
    reclaim_expired_delivery,
)
from tools.tests.factories import ToolExecutionFactory

pytestmark = pytest.mark.django_db


def _setup(monkeypatch, *, fake=None):
    fake = fake or FakeNotificationProvider()
    tool_execution = ToolExecutionFactory()
    workspace = tool_execution.workspace
    IntegrationConnectionFactory(workspace=workspace, provider=IntegrationProvider.EMAIL)
    monkeypatch.setattr("integrations.services.get_notification_provider", lambda provider: fake)
    return tool_execution, workspace, fake


# ---------------------------------------------------------------------------
# Creation / idempotency / snapshot
# ---------------------------------------------------------------------------


def test_creation_sets_notification_channel_and_frozen_snapshot(monkeypatch):
    tool_execution, workspace, _fake = _setup(monkeypatch)
    notification_delivery = create_or_reuse_notification_delivery(
        tool_execution=tool_execution,
        workspace=workspace,
        recipient_email="customer@example.com",
        subject="Hello",
        body="World",
    )
    assert notification_delivery.delivery.channel == DeliveryChannel.NOTIFICATION
    assert notification_delivery.delivery.status == DeliveryStatus.PENDING
    assert notification_delivery.medium == NotificationMedium.EMAIL
    assert notification_delivery.recipient_email == "customer@example.com"
    assert notification_delivery.subject == "Hello"
    assert notification_delivery.body == "World"
    assert notification_delivery.idempotency_key == f"notification.send:{tool_execution.id}"


def test_replay_of_same_tool_execution_reuses_existing_notification_delivery(monkeypatch):
    tool_execution, workspace, _fake = _setup(monkeypatch)
    first = create_or_reuse_notification_delivery(
        tool_execution=tool_execution,
        workspace=workspace,
        recipient_email="a@example.com",
        subject="s",
        body="b",
    )
    second = create_or_reuse_notification_delivery(
        tool_execution=tool_execution,
        workspace=workspace,
        recipient_email="a@example.com",
        subject="s",
        body="b",
    )
    assert first.pk == second.pk
    assert NotificationDelivery.objects.filter(source_tool_execution=tool_execution).count() == 1


def test_retry_delivers_original_frozen_snapshot_not_mutated_source(monkeypatch):
    from customers.tests.factories import CustomerFactory

    tool_execution, workspace, fake = _setup(monkeypatch)
    customer = CustomerFactory(workspace=workspace, email="original@example.com")

    notification_delivery = create_or_reuse_notification_delivery(
        tool_execution=tool_execution,
        workspace=workspace,
        recipient_email=customer.email,
        subject="Original subject",
        body="Original body",
    )
    # Mutate the source business record *after* the snapshot was taken.
    customer.email = "mutated@example.com"
    customer.save()

    delivery, token = claim_delivery(delivery_id=notification_delivery.delivery_id)
    handle_notification_delivery_attempt(delivery=delivery, claim_token=token)

    assert fake.outbox == [
        {"to": "original@example.com", "subject": "Original subject", "body": "Original body"}
    ]


# ---------------------------------------------------------------------------
# Success
# ---------------------------------------------------------------------------


def test_successful_send_marks_delivered_and_persists_provider_message_id(monkeypatch):
    tool_execution, workspace, fake = _setup(monkeypatch)
    notification_delivery = create_or_reuse_notification_delivery(
        tool_execution=tool_execution,
        workspace=workspace,
        recipient_email="a@example.com",
        subject="s",
        body="b",
    )
    delivery, token = claim_delivery(delivery_id=notification_delivery.delivery_id)
    handle_notification_delivery_attempt(delivery=delivery, claim_token=token)

    delivery.refresh_from_db()
    notification_delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DELIVERED
    assert delivery.delivered_at is not None
    assert delivery.claim_token is None
    assert (
        notification_delivery.provider_message_id
        == f"msg_fake_{notification_delivery.idempotency_key}"
    )
    attempt = DeliveryAttempt.objects.get(delivery=delivery, attempt_number=1)
    assert attempt.status == AttemptStatus.SUCCEEDED
    assert delivery.attempt_count == 1


# ---------------------------------------------------------------------------
# Failure classification (section 15, 19-20)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error_cls,code",
    [
        (IntegrationTemporarilyUnavailableError, "integration_temporarily_unavailable"),
        (IntegrationTimeoutError, "integration_timeout"),
        (IntegrationRateLimitedError, "integration_rate_limited"),
    ],
)
def test_retryable_provider_failure_schedules_retry(monkeypatch, error_cls, code):
    fake = FakeNotificationProvider(send_errors=[(error_cls(), False)])
    tool_execution, workspace, fake = _setup(monkeypatch, fake=fake)
    notification_delivery = create_or_reuse_notification_delivery(
        tool_execution=tool_execution,
        workspace=workspace,
        recipient_email="a@example.com",
        subject="s",
        body="b",
    )
    delivery, token = claim_delivery(delivery_id=notification_delivery.delivery_id)
    handle_notification_delivery_attempt(delivery=delivery, claim_token=token)

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.RETRY_SCHEDULED
    assert delivery.last_error_code == code
    assert delivery.next_attempt_at > timezone.now()
    assert delivery.claim_token is None
    assert delivery.claimed_at is None
    attempt = DeliveryAttempt.objects.get(delivery=delivery, attempt_number=1)
    assert attempt.retryable is True
    assert attempt.safe_error_code == code


# ---------------------------------------------------------------------------
# Ambiguous external success (Phase 10 Block 5, section 13-14, 19)
# ---------------------------------------------------------------------------


def test_ambiguous_timeout_after_provider_commit_is_deduplicated_by_stable_key(monkeypatch):
    """Models the most important ambiguous-success scenario honestly
    (section 14): the fake provider *records* the send (mirrors a remote
    mail server that accepted and queued the message) and only then raises
    a retryable timeout to the sender — the sender genuinely cannot tell
    whether the message went out. The retry reuses the exact same stable
    idempotency key (section 12), and this fake provider is capable of
    deduplicating on it — proving only one logical message exists — but
    this is a property of *this test double*, not a guarantee this
    platform can make about a real SMTP relay (documented explicitly
    below, not assumed)."""
    fake = FakeNotificationProvider(send_errors=[(IntegrationTimeoutError(), True)])
    tool_execution, workspace, fake = _setup(monkeypatch, fake=fake)
    notification_delivery = create_or_reuse_notification_delivery(
        tool_execution=tool_execution,
        workspace=workspace,
        recipient_email="a@example.com",
        subject="s",
        body="b",
    )
    stable_key = notification_delivery.idempotency_key

    # Attempt 1: the fake provider commits the send, then raises.
    delivery, token = claim_delivery(delivery_id=notification_delivery.delivery_id)
    handle_notification_delivery_attempt(delivery=delivery, claim_token=token)
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.RETRY_SCHEDULED
    assert fake.send_call_count == 1
    assert len(fake.outbox) == 1  # the ambiguous send already happened

    # Attempt 2: same stable key — the fake's own dedup returns the already
    # -committed result without incrementing its "new send" counter or
    # appending a second outbox entry.
    delivery, token = claim_delivery(
        delivery_id=notification_delivery.delivery_id, now=delivery.next_attempt_at
    )
    handle_notification_delivery_attempt(delivery=delivery, claim_token=token)
    delivery.refresh_from_db()

    assert delivery.status == DeliveryStatus.DELIVERED
    assert fake.send_call_count == 1, "the fake provider's own key-based dedup suppressed a resend"
    assert len(fake.outbox) == 1

    notification_delivery.refresh_from_db()
    assert notification_delivery.idempotency_key == stable_key
    assert notification_delivery.delivery_id == delivery.id
    # NOT a platform guarantee for a real SMTP/HTTP provider: a real mail
    # relay or webhook receiver that does not implement key-based dedup may
    # legitimately receive and act on this message twice under at-least-once
    # delivery — this fake's suppression is a test-double convenience, not
    # something ``notification.send`` enforces against arbitrary providers.


@pytest.mark.parametrize(
    "error_cls,code",
    [
        (IntegrationAuthenticationFailedError, "integration_authentication_failed"),
        (IntegrationConfigurationError, "integration_configuration_error"),
        (IntegrationInvalidRequestError, "integration_invalid_request"),
    ],
)
def test_terminal_provider_failure_marks_dead(monkeypatch, error_cls, code):
    fake = FakeNotificationProvider(send_errors=[(error_cls(), False)])
    tool_execution, workspace, fake = _setup(monkeypatch, fake=fake)
    notification_delivery = create_or_reuse_notification_delivery(
        tool_execution=tool_execution,
        workspace=workspace,
        recipient_email="a@example.com",
        subject="s",
        body="b",
    )
    delivery, token = claim_delivery(delivery_id=notification_delivery.delivery_id)
    handle_notification_delivery_attempt(delivery=delivery, claim_token=token)

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DEAD
    assert delivery.last_error_code == code
    attempt = DeliveryAttempt.objects.get(delivery=delivery, attempt_number=1)
    assert attempt.retryable is False
    # A DEAD delivery never automatically retries (section 20).
    with pytest.raises(DeliveryNotClaimableError):
        claim_delivery(delivery_id=delivery.id)


def test_unexpected_non_integration_exception_fails_closed(monkeypatch):
    tool_execution, workspace, _fake = _setup(monkeypatch)

    def _boom(**kwargs):
        raise RuntimeError("unexpected bug")

    monkeypatch.setattr("notifications.notification_delivery.send_notification", _boom)
    notification_delivery = create_or_reuse_notification_delivery(
        tool_execution=tool_execution,
        workspace=workspace,
        recipient_email="a@example.com",
        subject="s",
        body="b",
    )
    delivery, token = claim_delivery(delivery_id=notification_delivery.delivery_id)
    handle_notification_delivery_attempt(delivery=delivery, claim_token=token)

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DEAD
    assert delivery.last_error_code == UNEXPECTED_ERROR_CODE
    attempt = DeliveryAttempt.objects.get(delivery=delivery, attempt_number=1)
    assert attempt.retryable is False


def test_unexpected_error_never_logs_raw_exception_text(monkeypatch, caplog):
    """Block 2 remediation: the unexpected-provider-failure path must never
    log ``str(exc)``/``repr(exc)``/a traceback, only stable safe metadata —
    a secret embedded in an untrusted exception's message must never reach
    the log stream, regardless of formatter/DEBUG setting."""
    secret_marker = "SUPER_SECRET_NOTIFICATION_TOKEN_987654"
    tool_execution, workspace, _fake = _setup(monkeypatch)

    def _boom(**kwargs):
        raise RuntimeError(f"provider blew up while handling token={secret_marker}")

    monkeypatch.setattr("notifications.notification_delivery.send_notification", _boom)
    notification_delivery = create_or_reuse_notification_delivery(
        tool_execution=tool_execution,
        workspace=workspace,
        recipient_email="a@example.com",
        subject="s",
        body="b",
    )
    delivery, token = claim_delivery(delivery_id=notification_delivery.delivery_id)

    with caplog.at_level(logging.DEBUG, logger="supportpilot"):
        handle_notification_delivery_attempt(delivery=delivery, claim_token=token)

    assert secret_marker not in caplog.text
    matching = [r for r in caplog.records if getattr(r, "event", None) == UNEXPECTED_ERROR_CODE]
    assert len(matching) == 1
    record = matching[0]
    # No exc_info attached at all (never exc_info=True / logger.exception) —
    # the only thing identifying the exception is its class name.
    assert record.exc_info is None
    assert record.exception_type == "RuntimeError"
    assert secret_marker not in record.getMessage()

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DEAD
    assert delivery.last_error_code == UNEXPECTED_ERROR_CODE
    assert secret_marker not in delivery.last_error_code
    attempt = DeliveryAttempt.objects.get(delivery=delivery, attempt_number=1)
    assert attempt.safe_error_code == UNEXPECTED_ERROR_CODE
    assert secret_marker not in attempt.safe_error_code


# ---------------------------------------------------------------------------
# Max attempts (section 17)
# ---------------------------------------------------------------------------


def test_max_attempts_bounds_provider_call_count(monkeypatch, settings):
    settings.DELIVERY_RETRY_BASE_DELAY_SECONDS = 0
    fake = FakeNotificationProvider(
        send_errors=[(IntegrationTimeoutError(), False), (IntegrationTimeoutError(), False)]
    )
    tool_execution, workspace, fake = _setup(monkeypatch, fake=fake)

    delivery = create_delivery(
        workspace=workspace, channel=DeliveryChannel.NOTIFICATION, max_attempts=2
    )
    NotificationDelivery.objects.create(
        delivery=delivery,
        source_tool_execution=tool_execution,
        medium=NotificationMedium.EMAIL,
        recipient_email="a@example.com",
        subject="s",
        body="b",
        idempotency_key=f"notification.send:{tool_execution.id}",
    )

    for _ in range(5):
        try:
            claimed, token = claim_delivery(delivery_id=delivery.id)
        except DeliveryNotClaimableError:
            break
        handle_notification_delivery_attempt(delivery=claimed, claim_token=token)

    delivery.refresh_from_db()
    assert fake.send_call_count == 2
    assert delivery.attempt_count == 2
    assert delivery.status == DeliveryStatus.FAILED


# ---------------------------------------------------------------------------
# Stale-claim protection inherited from Block 1 (section 14, 29)
# ---------------------------------------------------------------------------


def test_stale_claim_protection_is_inherited_from_block1(monkeypatch):
    tool_execution, workspace, fake = _setup(monkeypatch)
    notification_delivery = create_or_reuse_notification_delivery(
        tool_execution=tool_execution,
        workspace=workspace,
        recipient_email="a@example.com",
        subject="s",
        body="b",
    )
    delivery, stale_token = claim_delivery(
        delivery_id=notification_delivery.delivery_id, lease_seconds=1
    )
    later = timezone.now() + timedelta(minutes=1)
    reclaim_expired_delivery(delivery_id=notification_delivery.delivery_id, now=later)

    with pytest.raises(StaleClaimError):
        handle_notification_delivery_attempt(delivery=delivery, claim_token=stale_token)


# ---------------------------------------------------------------------------
# Secret safety (section 27, 34)
# ---------------------------------------------------------------------------


def test_provider_failure_secret_like_text_never_persisted(monkeypatch):
    secret_marker = "hunter2-super-secret-password"
    fake = FakeNotificationProvider(
        send_errors=[
            (
                IntegrationTemporarilyUnavailableError(f"smtp failed, password={secret_marker}"),
                False,
            )
        ]
    )
    tool_execution, workspace, fake = _setup(monkeypatch, fake=fake)
    notification_delivery = create_or_reuse_notification_delivery(
        tool_execution=tool_execution,
        workspace=workspace,
        recipient_email="a@example.com",
        subject="s",
        body="b",
    )
    delivery, token = claim_delivery(delivery_id=notification_delivery.delivery_id)
    handle_notification_delivery_attempt(delivery=delivery, claim_token=token)

    delivery.refresh_from_db()
    assert delivery.last_error_code == "integration_temporarily_unavailable"
    assert secret_marker not in delivery.last_error_code
    attempt = DeliveryAttempt.objects.get(delivery=delivery, attempt_number=1)
    assert secret_marker not in attempt.safe_error_code


# ---------------------------------------------------------------------------
# Misc coverage: __str__, defensive missing-snapshot path, missing delivery
# ---------------------------------------------------------------------------


def test_notification_delivery_str_is_stable_and_safe(monkeypatch):
    tool_execution, workspace, _fake = _setup(monkeypatch)
    notification_delivery = create_or_reuse_notification_delivery(
        tool_execution=tool_execution,
        workspace=workspace,
        recipient_email="a@example.com",
        subject="s",
        body="b",
    )
    assert str(notification_delivery) == (
        f"{notification_delivery.delivery_id}:email:a@example.com"
    )


def test_missing_notification_snapshot_is_a_defensive_terminal_failure():
    """A Delivery with channel=NOTIFICATION but no ``NotificationDelivery``
    row is a data-integrity gap, not a real-world outcome this block's own
    producer can create — exercised directly against the handler."""
    from notifications.models import DeliveryChannel
    from notifications.tests.factories import DeliveryFactory

    delivery = DeliveryFactory(
        channel=DeliveryChannel.NOTIFICATION, next_attempt_at=timezone.now() - timedelta(seconds=1)
    )
    claimed, token = claim_delivery(delivery_id=delivery.id)
    handle_notification_delivery_attempt(delivery=claimed, claim_token=token)

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DEAD
    assert delivery.last_error_code == MISSING_SNAPSHOT_ERROR_CODE


def test_process_claimed_delivery_on_missing_delivery_id_is_a_safe_no_op():
    import uuid

    assert process_claimed_delivery(str(uuid.uuid4())) == "skipped"
