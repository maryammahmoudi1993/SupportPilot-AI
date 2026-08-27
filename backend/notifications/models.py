"""Durable delivery foundation (Phase 10 Block 1).

``Delivery`` is the single database-authoritative execution primitive shared
by every at-least-once outbound delivery this platform performs — outbound
notifications first, outbound webhooks next (Block 2/3 add the concrete
producers; neither exists yet, so this model deliberately carries no payload
or destination fields of its own, only the state machine that surrounds one).
``channel`` is the one discriminator that lets both future producers share
this table without a generic event-bus/CQRS abstraction (explicitly out of
scope for this block).

The database row — not Celery's delivery semantics, not in-process memory —
is the single source of truth for "who owns this delivery right now" and
"how many attempts has it had". A Celery task is disposable transport: it may
be duplicated, redelivered, or lost mid-flight, and none of that may corrupt
or duplicate the persisted state below (see ``notifications/services.py``).
"""

from __future__ import annotations

from django.db import models

from common.models import BaseModel


class DeliveryChannel(models.TextChoices):
    NOTIFICATION = "notification", "Notification"
    WEBHOOK = "webhook", "Webhook"


class DeliveryStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CLAIMED = "claimed", "Claimed"
    RETRY_SCHEDULED = "retry_scheduled", "Retry scheduled"
    DELIVERED = "delivered", "Delivered"
    FAILED = "failed", "Failed"
    # Distinct from FAILED (retry exhaustion): a DEAD delivery was terminated
    # by an explicitly non-retryable attempt outcome (attempt.retryable is
    # False) — retrying it would never succeed, so it never re-enters the
    # retry schedule regardless of remaining attempt budget.
    DEAD = "dead", "Dead"


# Terminal states never reopen through the normal claim/complete services
# below (section 26 of the repository conventions: explicit lifecycles never
# silently reopen). Recovery/replay of a terminal delivery, if ever needed,
# is a distinct, explicit operation — not a side effect of claiming.
DELIVERY_TERMINAL_STATUSES = frozenset(
    {DeliveryStatus.DELIVERED, DeliveryStatus.FAILED, DeliveryStatus.DEAD}
)

# States a delivery may be claimed *from* directly (subject to
# ``next_attempt_at`` being due). CLAIMED is claimable too, but only via
# reclaim once its lease has expired — see ``notifications/services.py``.
DELIVERY_DUE_CLAIMABLE_STATUSES = frozenset(
    {DeliveryStatus.PENDING, DeliveryStatus.RETRY_SCHEDULED}
)


class AttemptStatus(models.TextChoices):
    IN_PROGRESS = "in_progress", "In progress"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"


class Delivery(BaseModel):
    """One logical at-least-once delivery. Every operational field below is
    server-owned (section 23) — no serializer/API in this or any future
    block may accept these as client input; they only ever change through
    ``notifications/services.py``."""

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="deliveries"
    )
    channel = models.CharField(max_length=20, choices=DeliveryChannel.choices)
    status = models.CharField(
        max_length=20, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING
    )

    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField()

    # When this delivery next becomes eligible for a claim. Set to "now" on
    # creation (immediately due) and advanced only by
    # ``complete_delivery_failure`` scheduling a retry.
    next_attempt_at = models.DateTimeField()

    # The active claim, if any. All three are set together and cleared
    # together — never independently (see the DB constraint below).
    claimed_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    claim_token = models.UUIDField(null=True, blank=True)

    first_attempt_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(attempt_count__gte=0), name="delivery_attempt_count_gte_0"
            ),
            models.CheckConstraint(
                condition=models.Q(max_attempts__gt=0), name="delivery_max_attempts_gt_0"
            ),
            models.CheckConstraint(
                condition=models.Q(attempt_count__lte=models.F("max_attempts")),
                name="delivery_attempt_count_lte_max",
            ),
            # Claim field consistency (section 18): CLAIMED always carries a
            # full claim identity; any other status never does. This makes
            # "claim_token is not null" alone a reliable ownership signal.
            models.CheckConstraint(
                condition=models.Q(status="claimed")
                & models.Q(claimed_at__isnull=False)
                & models.Q(lease_expires_at__isnull=False)
                & models.Q(claim_token__isnull=False)
                | ~models.Q(status="claimed")
                & models.Q(claimed_at__isnull=True)
                & models.Q(lease_expires_at__isnull=True)
                & models.Q(claim_token__isnull=True),
                name="delivery_claim_fields_consistent",
            ),
        ]
        indexes = [
            # Due-work selector: "give me claimable PENDING/RETRY_SCHEDULED
            # rows" filters on exactly these two columns.
            models.Index(fields=["status", "next_attempt_at"], name="delivery_status_due_idx"),
            # Expired-lease selector for the future reclaim sweeper (Block 4)
            # filters CLAIMED rows by lease_expires_at; a plain index on the
            # column is sufficient since status is highly selective already
            # via the query's own equality filter.
            models.Index(fields=["lease_expires_at"], name="delivery_lease_expires_idx"),
            # Workspace-scoped listing/lookup, newest first.
            models.Index(fields=["workspace", "created_at"], name="delivery_ws_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.id}:{self.channel}:{self.status}"


class DeliveryAttempt(BaseModel):
    """One bounded operational attempt slot for a ``Delivery``. Never stores
    a response body, exception repr, or credentials (section 10) — only the
    safe, structured outcome of one attempt."""

    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE, related_name="attempts")
    attempt_number = models.PositiveIntegerField()
    # The claim token active during this attempt — the same value proves
    # ownership at completion time (see ``services.py``). Not logged
    # (section 28) but safe to persist for auditability of which claim
    # produced which attempt.
    claim_token = models.UUIDField()
    status = models.CharField(
        max_length=20, choices=AttemptStatus.choices, default=AttemptStatus.IN_PROGRESS
    )

    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)

    safe_error_code = models.CharField(max_length=64, blank=True)
    # Only meaningful once status is FAILED; null otherwise.
    retryable = models.BooleanField(null=True, blank=True)

    # Unused until webhook HTTP delivery exists (Block 3) — reserved now so
    # that block does not need a follow-up migration for it.
    response_status_code = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["delivery", "attempt_number"]
        constraints = [
            # Deterministic, DB-safe attempt numbering (section 11): two
            # concurrent claims can never both persist attempt N for the
            # same delivery, regardless of what races in Python memory.
            models.UniqueConstraint(
                fields=["delivery", "attempt_number"], name="delivery_attempt_number_uniq"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.delivery_id}:{self.attempt_number}:{self.status}"


class NotificationMedium(models.TextChoices):
    """The notification *medium* — deliberately a distinct concept from
    ``Delivery.channel`` (section 6), which distinguishes logical delivery
    *families* (notification vs. webhook), not the medium within one family.
    Only email exists today, matching the sole Phase 7 ``NotificationProvider``
    adapter (``integrations.providers.email_provider``)."""

    EMAIL = "email", "Email"


class NotificationDelivery(BaseModel):
    """The notification-specific one-to-one companion to a ``Delivery``
    (section 5): everything Block 1's generic delivery lifecycle doesn't
    need to know about — the frozen recipient/content snapshot and the
    stable provider-facing idempotency identity. Never stores credentials or
    other provider secrets (section 27) — only the same non-secret
    recipient/subject/body a human already sees in the tool call.

    One row per source ``ToolExecution`` (the ``OneToOneField`` below is the
    database-enforced identity, section 11): a replayed/reset
    ``notification.send`` execution finds and reuses this row rather than
    creating a second logical notification.
    """

    delivery = models.OneToOneField(
        Delivery, on_delete=models.CASCADE, related_name="notification_delivery"
    )
    source_tool_execution = models.OneToOneField(
        "tools.ToolExecution", on_delete=models.PROTECT, related_name="notification_delivery"
    )
    medium = models.CharField(max_length=20, choices=NotificationMedium.choices)

    # Frozen at creation time (section 7) — never re-read from the current
    # Customer/business record on retry. Deliberately plain columns, not a
    # JSON blob (section 5): the existing notification provider contract
    # already fixes exactly these three fields.
    recipient_email = models.EmailField()
    subject = models.CharField(max_length=200)
    body = models.TextField()

    # The stable identity passed to ``NotificationProvider.send`` on *every*
    # attempt for this delivery (section 12) — never regenerated per retry,
    # so a provider that supports idempotency (or the deterministic fake)
    # can deduplicate an ambiguous retry after a timeout.
    idempotency_key = models.CharField(max_length=200)

    # Set once the provider supplies one on a successful send (section 21).
    # Never asserted to exist for providers/outcomes that don't return one.
    provider_message_id = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(recipient_email=""),
                name="notification_delivery_recipient_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(idempotency_key=""),
                name="notification_delivery_idempotency_key_not_blank",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.delivery_id}:{self.medium}:{self.recipient_email}"
