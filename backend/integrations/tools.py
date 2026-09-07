"""Business tools backed by the integration layer (section 5, 27-59).

Every handler here is a thin, typed bridge: resolve trusted context ->
tenant-scoped internal lookup or ``integrations.services`` call -> map any
``IntegrationError`` into the Phase 6 ``ToolError`` taxonomy via
``IntegrationToolError``. No handler talks to a provider adapter, decrypts
a credential, or accepts a workspace/connection identifier as an argument —
every one of those is server-derived from ``ToolExecutionContext`` or a
tenant-scoped selector, never model input (section 9, 27-28, 70, 106-108).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from rest_framework.exceptions import ValidationError as DRFValidationError

from accounts.models import User
from audit.models import AuditAction
from audit.services import record_event
from customers import selectors as customer_selectors
from notifications.notification_delivery import create_or_reuse_notification_delivery
from tickets import selectors as ticket_selectors
from tickets import services as ticket_services
from tickets.models import TicketPriority, TicketStatus
from tools.contracts import (
    IdempotencyMode,
    RetryPolicy,
    RiskLevel,
    SideEffectType,
    Tool,
    ToolExecutionContext,
    ToolSpec,
)
from tools.errors import ToolError, ToolTimeoutError
from tools.models import ToolExecution
from workspaces.models import Workspace

from . import services as integration_services
from .errors import (
    RETRYABLE_INTEGRATION_CODES,
    CustomerNotFoundError,
    IntegrationError,
    IntegrationInvalidRequestError,
    IntegrationMalformedResponseError,
    IntegrationRateLimitedError,
    IntegrationTemporarilyUnavailableError,
    IntegrationTimeoutError,
    TicketNotFoundError,
)
from .schemas import EmailAddress

MAX_TEXT_LENGTH = 5000


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntegrationToolError(ToolError):
    """Bridges a normalized ``IntegrationError`` into ``tools.errors.ToolError``
    so it flows through the existing Phase 6 execution/persistence/redaction
    path unchanged — there is no second error-handling path (section 9, 20)."""

    def __init__(self, integration_error: IntegrationError) -> None:
        self.code = integration_error.code
        self.retryable = integration_error.retryable
        super().__init__(integration_error.safe_message)


#: Write operations never auto-retry on an ambiguous timeout (section 43,
#: 92): a rate limit or a provider-reported outage is safe to retry because
#: the provider-level idempotency key is stable across retries, but a
#: timeout means the outcome is genuinely unknown, so it is deliberately
#: excluded here — a caller must explicitly retry (safely, thanks to that
#: same stable key) rather than have Phase 6 loop on it automatically.
WRITE_RETRYABLE_CODES = frozenset(
    {IntegrationRateLimitedError.code, IntegrationTemporarilyUnavailableError.code}
)
READ_RETRYABLE_CODES = RETRYABLE_INTEGRATION_CODES

#: Phase 16 Checkpoint 4 (Part A): error codes meaning the provider's own
#: commit outcome is genuinely unknown — the request may have already
#: succeeded before the client observed the failure. Safe to leave out of
#: ``WRITE_RETRYABLE_CODES`` (never auto-retried in-process) is not enough
#: on its own: ``tools.execution._resolve_existing`` still lets a *manual*
#: same-idempotency-key retry reset an ordinary terminal failure back to
#: ``PENDING`` and call the handler again. For ``payment.refund`` that is
#: safe because Stripe deduplicates by the reused idempotency key
#: server-side; ``calendar.create_booking`` has no such provider-side
#: dedup (see ``integrations/providers/google_calendar.py``), so a second
#: call for the same logical booking is a second real event. This set is
#: assigned to that tool's ``RetryPolicy.ambiguous_outcome_error_codes`` to
#: refuse *any* retry (automatic or manual) of a call left in this state,
#: rather than silently risking a duplicate. Includes ``ToolTimeoutError``
#: (``tools.execution``'s own wall-clock enforcement cutting the handler
#: off) alongside the two provider-reported codes — that cutoff is exactly
#: as ambiguous as a provider-reported timeout: the request may already
#: have reached and been committed by Google before the deadline expired.
CALENDAR_AMBIGUOUS_OUTCOME_CODES = frozenset(
    {
        IntegrationTimeoutError.code,
        IntegrationMalformedResponseError.code,
        ToolTimeoutError.code,
    }
)


def _workspace(context: ToolExecutionContext) -> Workspace:
    return Workspace.objects.get(pk=context.workspace_id)


def _remaining_seconds(context: ToolExecutionContext) -> float:
    return max((context.deadline - timezone.now()).total_seconds(), 0.5)


def _actor(context: ToolExecutionContext) -> User | None:
    if not context.actor_user_id:
        return None
    return User.objects.filter(pk=context.actor_user_id).first()


# ---------------------------------------------------------------------------
# customer.lookup
# ---------------------------------------------------------------------------


class CustomerLookupInput(StrictModel):
    customer_id: str | None = Field(default=None, max_length=64)
    email: EmailAddress | None = None
    external_reference: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _exactly_one_identifier(self) -> CustomerLookupInput:
        provided = [v for v in (self.customer_id, self.email, self.external_reference) if v]
        if len(provided) != 1:
            raise ValueError("Provide exactly one of customer_id, email, or external_reference.")
        return self


class CustomerLookupOutput(StrictModel):
    customer_id: str
    display_name: str
    email: str | None
    company: str
    is_active: bool
    external_reference: str | None


def _customer_lookup_handler(*, context: ToolExecutionContext, arguments: BaseModel) -> BaseModel:
    assert isinstance(arguments, CustomerLookupInput)
    workspace = _workspace(context)
    if arguments.customer_id:
        customer = customer_selectors.customer_get_by_id_for_workspace(
            workspace=workspace, customer_id=arguments.customer_id
        )
    elif arguments.email:
        customer = customer_selectors.customer_get_by_email_for_workspace(
            workspace=workspace, email=str(arguments.email)
        )
    else:
        # The "exactly one identifier" model validator guarantees this is
        # non-None whenever the first two branches are not taken.
        assert arguments.external_reference is not None
        customer = customer_selectors.customer_get_by_external_id_for_workspace(
            workspace=workspace, external_id=arguments.external_reference
        )
    if customer is None:
        raise IntegrationToolError(CustomerNotFoundError())
    return CustomerLookupOutput(
        customer_id=str(customer.id),
        display_name=customer.display_name,
        email=customer.email,
        company=customer.company,
        is_active=customer.is_active,
        external_reference=customer.external_id,
    )


CUSTOMER_LOOKUP_TOOL = Tool(
    spec=ToolSpec(
        key="customer.lookup",
        display_name="Customer lookup",
        description="Look up a workspace customer by ID, email, or external reference.",
        input_model=CustomerLookupInput,
        output_model=CustomerLookupOutput,
        risk_level=RiskLevel.READ_ONLY,
        side_effect_type=SideEffectType.READ,
        default_timeout_seconds=5.0,
        max_timeout_seconds=10.0,
        retry_policy=RetryPolicy(max_retries=0),
        idempotency_mode=IdempotencyMode.SAFE,
    ),
    handler=_customer_lookup_handler,
)


# ---------------------------------------------------------------------------
# order.lookup / shipment.lookup
# ---------------------------------------------------------------------------


class OrderLookupInput(StrictModel):
    order_reference: str = Field(min_length=1, max_length=128)


class OrderLookupOutput(StrictModel):
    order_id: str
    external_order_id: str
    status: str
    created_at: datetime
    amount_minor: int
    currency: str
    shipment_status: str | None
    tracking_reference: str | None


def _order_lookup_handler(*, context: ToolExecutionContext, arguments: BaseModel) -> BaseModel:
    assert isinstance(arguments, OrderLookupInput)
    workspace = _workspace(context)
    try:
        order = integration_services.get_order(
            workspace=workspace,
            remaining_seconds=_remaining_seconds(context),
            order_reference=arguments.order_reference,
        )
    except IntegrationError as exc:
        raise IntegrationToolError(exc) from exc
    return OrderLookupOutput(
        order_id=order.order_id,
        external_order_id=order.external_order_id,
        status=order.status,
        created_at=order.created_at,
        amount_minor=order.amount_minor,
        currency=order.currency,
        shipment_status=order.shipment_status,
        tracking_reference=order.tracking_reference,
    )


ORDER_LOOKUP_TOOL = Tool(
    spec=ToolSpec(
        key="order.lookup",
        display_name="Order lookup",
        description="Look up an order's status, amount, and shipment summary.",
        input_model=OrderLookupInput,
        output_model=OrderLookupOutput,
        risk_level=RiskLevel.READ_ONLY,
        side_effect_type=SideEffectType.READ,
        default_timeout_seconds=8.0,
        max_timeout_seconds=15.0,
        retry_policy=RetryPolicy(max_retries=2, retryable_error_codes=READ_RETRYABLE_CODES),
        idempotency_mode=IdempotencyMode.SAFE,
    ),
    handler=_order_lookup_handler,
)


class ShipmentLookupInput(StrictModel):
    shipment_reference: str = Field(min_length=1, max_length=128)


class ShipmentLookupOutput(StrictModel):
    shipment_id: str
    order_id: str
    status: str
    tracking_reference: str | None
    carrier: str | None
    estimated_delivery: datetime | None


def _shipment_lookup_handler(*, context: ToolExecutionContext, arguments: BaseModel) -> BaseModel:
    assert isinstance(arguments, ShipmentLookupInput)
    workspace = _workspace(context)
    try:
        shipment = integration_services.get_shipment(
            workspace=workspace,
            remaining_seconds=_remaining_seconds(context),
            shipment_reference=arguments.shipment_reference,
        )
    except IntegrationError as exc:
        raise IntegrationToolError(exc) from exc
    return ShipmentLookupOutput(
        shipment_id=shipment.shipment_id,
        order_id=shipment.order_id,
        status=shipment.status,
        tracking_reference=shipment.tracking_reference,
        carrier=shipment.carrier,
        estimated_delivery=shipment.estimated_delivery,
    )


SHIPMENT_LOOKUP_TOOL = Tool(
    spec=ToolSpec(
        key="shipment.lookup",
        display_name="Shipment lookup",
        description="Look up a shipment's tracking status and carrier.",
        input_model=ShipmentLookupInput,
        output_model=ShipmentLookupOutput,
        risk_level=RiskLevel.READ_ONLY,
        side_effect_type=SideEffectType.READ,
        default_timeout_seconds=8.0,
        max_timeout_seconds=15.0,
        retry_policy=RetryPolicy(max_retries=2, retryable_error_codes=READ_RETRYABLE_CODES),
        idempotency_mode=IdempotencyMode.SAFE,
    ),
    handler=_shipment_lookup_handler,
)


# ---------------------------------------------------------------------------
# payment.lookup / payment.refund
# ---------------------------------------------------------------------------


class PaymentLookupInput(StrictModel):
    payment_reference: str = Field(min_length=1, max_length=128)


class PaymentLookupOutput(StrictModel):
    payment_id: str
    external_payment_id: str
    status: str
    amount_minor: int
    currency: str
    created_at: datetime
    refunded_amount_minor: int


def _payment_lookup_handler(*, context: ToolExecutionContext, arguments: BaseModel) -> BaseModel:
    assert isinstance(arguments, PaymentLookupInput)
    workspace = _workspace(context)
    try:
        payment = integration_services.get_payment(
            workspace=workspace,
            remaining_seconds=_remaining_seconds(context),
            payment_reference=arguments.payment_reference,
        )
    except IntegrationError as exc:
        raise IntegrationToolError(exc) from exc
    return PaymentLookupOutput(
        payment_id=payment.payment_id,
        external_payment_id=payment.external_payment_id,
        status=payment.status,
        amount_minor=payment.amount_minor,
        currency=payment.currency,
        created_at=payment.created_at,
        refunded_amount_minor=payment.refunded_amount_minor,
    )


PAYMENT_LOOKUP_TOOL = Tool(
    spec=ToolSpec(
        key="payment.lookup",
        display_name="Payment lookup",
        description="Look up a payment's status and refunded amount.",
        input_model=PaymentLookupInput,
        output_model=PaymentLookupOutput,
        risk_level=RiskLevel.READ_ONLY,
        side_effect_type=SideEffectType.READ,
        default_timeout_seconds=8.0,
        max_timeout_seconds=15.0,
        retry_policy=RetryPolicy(max_retries=2, retryable_error_codes=READ_RETRYABLE_CODES),
        idempotency_mode=IdempotencyMode.SAFE,
    ),
    handler=_payment_lookup_handler,
)


class PaymentRefundInput(StrictModel):
    payment_reference: str = Field(min_length=1, max_length=128)
    amount_minor: int = Field(gt=0, le=100_000_000)
    currency: str = Field(min_length=3, max_length=3)
    reason: str = Field(default="requested_by_customer", max_length=200)

    @field_validator("currency")
    @classmethod
    def _currency_upper(cls, value: str) -> str:
        return value.upper()


class PaymentRefundOutput(StrictModel):
    refund_id: str
    payment_id: str
    status: str
    amount_minor: int
    currency: str
    created_at: datetime


def _payment_refund_handler(*, context: ToolExecutionContext, arguments: BaseModel) -> BaseModel:
    assert isinstance(arguments, PaymentRefundInput)
    workspace = _workspace(context)
    # Stable across every retry of *this* logical ToolExecution row (Phase 6
    # resets the same row to PENDING and re-invokes the handler on retry —
    # see tools/execution.py:_resolve_existing) — never a fresh key per
    # attempt (section 40-41).
    idempotency_key = f"payment.refund:{context.tool_execution_id}"
    try:
        refund = integration_services.refund_payment(
            workspace=workspace,
            remaining_seconds=_remaining_seconds(context),
            payment_reference=arguments.payment_reference,
            amount_minor=arguments.amount_minor,
            currency=arguments.currency,
            reason=arguments.reason,
            idempotency_key=idempotency_key,
        )
    except IntegrationError as exc:
        raise IntegrationToolError(exc) from exc

    # Phase 7 proves execution mechanics only; Phase 8 decides *whether* a
    # refund is authorized (section 39). A successfully executed sandbox
    # refund is still a high-risk financial action worth its own audit
    # record in addition to the Phase 6 ToolExecution (section 122).
    record_event(
        action=AuditAction.PAYMENT_REFUND_EXECUTED,
        target_type="payment",
        target_id=refund.payment_id,
        actor=_actor(context),
        workspace=workspace,
        metadata={
            "tool_execution_id": context.tool_execution_id,
            "agent_run_id": context.agent_run_id,
            "refund_id": refund.refund_id,
            "amount_minor": refund.amount_minor,
            "currency": refund.currency,
        },
        request_id=context.correlation_id,
    )
    return PaymentRefundOutput(
        refund_id=refund.refund_id,
        payment_id=refund.payment_id,
        status=refund.status,
        amount_minor=refund.amount_minor,
        currency=refund.currency,
        created_at=refund.created_at,
    )


PAYMENT_REFUND_TOOL = Tool(
    spec=ToolSpec(
        key="payment.refund",
        display_name="Payment refund",
        description=(
            "Execute a sandbox refund against a payment. Phase 7 proves execution "
            "mechanics only; deterministic authorization policy and human approval "
            "gates are added in Phase 8 — do not treat a successful call here as a "
            "business decision that this refund was permitted."
        ),
        input_model=PaymentRefundInput,
        output_model=PaymentRefundOutput,
        risk_level=RiskLevel.CRITICAL,
        side_effect_type=SideEffectType.FINANCIAL,
        default_timeout_seconds=10.0,
        max_timeout_seconds=15.0,
        retry_policy=RetryPolicy(max_retries=2, retryable_error_codes=WRITE_RETRYABLE_CODES),
        idempotency_mode=IdempotencyMode.REQUIRED,
    ),
    handler=_payment_refund_handler,
)


# ---------------------------------------------------------------------------
# calendar.check_availability / calendar.create_booking
# ---------------------------------------------------------------------------


def _require_tz_aware_range(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware.")
    if start >= end:
        raise ValueError("start must be before end.")


class CalendarAvailabilityInput(StrictModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def _valid_range(self) -> CalendarAvailabilityInput:
        _require_tz_aware_range(self.start, self.end)
        return self


class AvailabilitySlotOutput(StrictModel):
    start: datetime
    end: datetime


class CalendarAvailabilityOutput(StrictModel):
    slots: list[AvailabilitySlotOutput]


def _within_scheduling_horizon(moment: datetime) -> bool:
    horizon = timedelta(days=settings.INTEGRATIONS_CALENDAR_MAX_HORIZON_DAYS)
    return moment <= timezone.now() + horizon


def _calendar_availability_handler(
    *, context: ToolExecutionContext, arguments: BaseModel
) -> BaseModel:
    assert isinstance(arguments, CalendarAvailabilityInput)
    workspace = _workspace(context)
    if not _within_scheduling_horizon(arguments.start):
        raise IntegrationToolError(
            IntegrationInvalidRequestError("Requested window exceeds the scheduling horizon.")
        )
    try:
        slots = integration_services.get_availability(
            workspace=workspace,
            remaining_seconds=_remaining_seconds(context),
            window_start=arguments.start,
            window_end=arguments.end,
        )
    except IntegrationError as exc:
        raise IntegrationToolError(exc) from exc
    return CalendarAvailabilityOutput(
        slots=[AvailabilitySlotOutput(start=slot.start, end=slot.end) for slot in slots]
    )


CALENDAR_AVAILABILITY_TOOL = Tool(
    spec=ToolSpec(
        key="calendar.check_availability",
        display_name="Calendar availability",
        description="Check free/busy availability for a bounded time window.",
        input_model=CalendarAvailabilityInput,
        output_model=CalendarAvailabilityOutput,
        risk_level=RiskLevel.READ_ONLY,
        side_effect_type=SideEffectType.READ,
        default_timeout_seconds=8.0,
        max_timeout_seconds=15.0,
        retry_policy=RetryPolicy(max_retries=2, retryable_error_codes=READ_RETRYABLE_CODES),
        idempotency_mode=IdempotencyMode.SAFE,
    ),
    handler=_calendar_availability_handler,
)


class CalendarBookingInput(StrictModel):
    start: datetime
    end: datetime
    title: str = Field(min_length=1, max_length=200)
    customer_id: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def _valid_range(self) -> CalendarBookingInput:
        _require_tz_aware_range(self.start, self.end)
        return self


class CalendarBookingOutput(StrictModel):
    booking_id: str
    external_event_id: str
    start: datetime
    end: datetime
    status: str


def _calendar_booking_handler(*, context: ToolExecutionContext, arguments: BaseModel) -> BaseModel:
    assert isinstance(arguments, CalendarBookingInput)
    workspace = _workspace(context)
    if not _within_scheduling_horizon(arguments.start):
        raise IntegrationToolError(
            IntegrationInvalidRequestError("Requested time exceeds the scheduling horizon.")
        )
    if len(arguments.title) > settings.INTEGRATIONS_CALENDAR_MAX_TITLE_LENGTH:
        raise IntegrationToolError(IntegrationInvalidRequestError("Title is too long."))
    customer = customer_selectors.customer_get_by_id_for_workspace(
        workspace=workspace, customer_id=arguments.customer_id
    )
    if customer is None:
        raise IntegrationToolError(CustomerNotFoundError())

    idempotency_key = f"calendar.create_booking:{context.tool_execution_id}"
    try:
        booking = integration_services.create_booking(
            workspace=workspace,
            remaining_seconds=_remaining_seconds(context),
            start=arguments.start,
            end=arguments.end,
            title=arguments.title,
            # Attendee identity is always derived from the tenant-scoped
            # customer record, never a free-form argument (section 58).
            attendee_email=customer.email,
            idempotency_key=idempotency_key,
        )
    except IntegrationError as exc:
        raise IntegrationToolError(exc) from exc
    return CalendarBookingOutput(
        booking_id=booking.booking_id,
        external_event_id=booking.external_event_id,
        start=booking.start,
        end=booking.end,
        status=booking.status,
    )


CALENDAR_BOOKING_TOOL = Tool(
    spec=ToolSpec(
        key="calendar.create_booking",
        display_name="Calendar booking",
        description="Create a calendar booking for a workspace customer.",
        input_model=CalendarBookingInput,
        output_model=CalendarBookingOutput,
        risk_level=RiskLevel.HIGH,
        side_effect_type=SideEffectType.EXTERNAL_WRITE,
        default_timeout_seconds=10.0,
        max_timeout_seconds=15.0,
        retry_policy=RetryPolicy(
            max_retries=2,
            retryable_error_codes=WRITE_RETRYABLE_CODES,
            ambiguous_outcome_error_codes=CALENDAR_AMBIGUOUS_OUTCOME_CODES,
        ),
        idempotency_mode=IdempotencyMode.REQUIRED,
    ),
    handler=_calendar_booking_handler,
)


# ---------------------------------------------------------------------------
# ticket.create / ticket.update
# ---------------------------------------------------------------------------


class TicketCreateInput(StrictModel):
    customer_id: str = Field(min_length=1, max_length=64)
    subject: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=MAX_TEXT_LENGTH)
    priority: str | None = None

    @field_validator("priority")
    @classmethod
    def _valid_priority(cls, value: str | None) -> str | None:
        if value is not None and value not in TicketPriority.values:
            raise ValueError("Invalid priority.")
        return value


class TicketSummary(StrictModel):
    ticket_id: str
    status: str
    priority: str
    subject: str


def _ticket_create_handler(*, context: ToolExecutionContext, arguments: BaseModel) -> BaseModel:
    assert isinstance(arguments, TicketCreateInput)
    workspace = _workspace(context)
    customer = customer_selectors.customer_get_by_id_for_workspace(
        workspace=workspace, customer_id=arguments.customer_id
    )
    if customer is None:
        raise IntegrationToolError(CustomerNotFoundError())
    ticket = ticket_services.create_ticket(
        workspace=workspace,
        customer=customer,
        subject=arguments.subject,
        description=arguments.description,
        priority=arguments.priority,
    )
    return TicketSummary(
        ticket_id=str(ticket.id),
        status=ticket.status,
        priority=ticket.priority,
        subject=ticket.subject,
    )


TICKET_CREATE_TOOL = Tool(
    spec=ToolSpec(
        key="ticket.create",
        display_name="Create ticket",
        description="Create a support ticket for a workspace customer.",
        input_model=TicketCreateInput,
        output_model=TicketSummary,
        risk_level=RiskLevel.MEDIUM,
        side_effect_type=SideEffectType.INTERNAL_WRITE,
        default_timeout_seconds=5.0,
        max_timeout_seconds=10.0,
        # No external provider call — a transient failure here is a
        # programming/DB error, not something retrying blindly would fix,
        # and retrying could create a duplicate ticket.
        retry_policy=RetryPolicy(max_retries=0),
        idempotency_mode=IdempotencyMode.REQUIRED,
    ),
    handler=_ticket_create_handler,
)


class TicketUpdateInput(StrictModel):
    ticket_id: str = Field(min_length=1, max_length=64)
    status: str | None = None
    priority: str | None = None
    note: str | None = Field(default=None, max_length=MAX_TEXT_LENGTH)

    @field_validator("status")
    @classmethod
    def _valid_status(cls, value: str | None) -> str | None:
        if value is not None and value not in TicketStatus.values:
            raise ValueError("Invalid status.")
        return value

    @field_validator("priority")
    @classmethod
    def _valid_priority(cls, value: str | None) -> str | None:
        if value is not None and value not in TicketPriority.values:
            raise ValueError("Invalid priority.")
        return value


def _ticket_update_handler(*, context: ToolExecutionContext, arguments: BaseModel) -> BaseModel:
    assert isinstance(arguments, TicketUpdateInput)
    workspace = _workspace(context)
    ticket = ticket_selectors.ticket_get_by_id_for_workspace(
        workspace=workspace, ticket_id=arguments.ticket_id
    )
    if ticket is None:
        raise IntegrationToolError(TicketNotFoundError())
    try:
        ticket = ticket_services.apply_agent_ticket_update(
            workspace=workspace,
            ticket=ticket,
            actor=_actor(context),
            priority=arguments.priority,
            status=arguments.status,
            note=arguments.note,
        )
    except DRFValidationError as exc:
        raise IntegrationToolError(
            IntegrationInvalidRequestError(_first_validation_message(exc))
        ) from exc
    return TicketSummary(
        ticket_id=str(ticket.id),
        status=ticket.status,
        priority=ticket.priority,
        subject=ticket.subject,
    )


def _first_validation_message(exc: DRFValidationError) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        for value in detail.values():
            if isinstance(value, list) and value:
                return str(value[0])
    return "Invalid ticket update."


TICKET_UPDATE_TOOL = Tool(
    spec=ToolSpec(
        key="ticket.update",
        display_name="Update ticket",
        description="Update a support ticket's status, priority, or add a note.",
        input_model=TicketUpdateInput,
        output_model=TicketSummary,
        risk_level=RiskLevel.MEDIUM,
        side_effect_type=SideEffectType.INTERNAL_WRITE,
        default_timeout_seconds=5.0,
        max_timeout_seconds=10.0,
        retry_policy=RetryPolicy(max_retries=0),
        idempotency_mode=IdempotencyMode.REQUIRED,
    ),
    handler=_ticket_update_handler,
)


# ---------------------------------------------------------------------------
# notification.send
# ---------------------------------------------------------------------------


class NotificationSendInput(StrictModel):
    customer_id: str = Field(min_length=1, max_length=64)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)


class NotificationSendOutput(StrictModel):
    #: Phase 10 Block 2: the tool no longer performs synchronous provider
    #: I/O, so it never reports "sent" — only that a durable delivery was
    #: accepted for asynchronous processing (section 8). Actual send/retry
    #: outcomes live on the ``Delivery``/``DeliveryAttempt`` rows, not here.
    status: str = "queued"
    delivery_id: str


def _notification_send_handler(*, context: ToolExecutionContext, arguments: BaseModel) -> BaseModel:
    assert isinstance(arguments, NotificationSendInput)
    workspace = _workspace(context)
    if len(arguments.subject) > settings.INTEGRATIONS_NOTIFICATION_MAX_SUBJECT_LENGTH:
        raise IntegrationToolError(IntegrationInvalidRequestError("Subject is too long."))
    if len(arguments.body) > settings.INTEGRATIONS_NOTIFICATION_MAX_BODY_LENGTH:
        raise IntegrationToolError(IntegrationInvalidRequestError("Body is too long."))
    customer = customer_selectors.customer_get_by_id_for_workspace(
        workspace=workspace, customer_id=arguments.customer_id
    )
    if customer is None:
        raise IntegrationToolError(CustomerNotFoundError())
    if not customer.email:
        raise IntegrationToolError(IntegrationInvalidRequestError("Customer has no email on file."))
    # A usable EMAIL integration must exist *now* — section 8's tool
    # contract still validates configuration synchronously, it just no
    # longer performs the provider call itself. Raising here (instead of
    # only discovering "not configured" inside the async worker) keeps the
    # existing, tested "integration_not_configured"/"integration_disabled"
    # tool-error behavior unchanged for a workspace with no EMAIL
    # connection at all.
    integration_services.ensure_notification_provider_configured(workspace=workspace)

    tool_execution = ToolExecution.objects.get(pk=context.tool_execution_id)
    notification_delivery = create_or_reuse_notification_delivery(
        tool_execution=tool_execution,
        workspace=workspace,
        # Recipient is always the tenant-scoped customer's own address —
        # never a raw argument (section 58).
        recipient_email=customer.email,
        subject=arguments.subject,
        body=arguments.body,
    )
    return NotificationSendOutput(delivery_id=str(notification_delivery.delivery_id))


NOTIFICATION_SEND_TOOL = Tool(
    spec=ToolSpec(
        key="notification.send",
        display_name="Send customer notification",
        description="Send an email notification to a workspace customer.",
        input_model=NotificationSendInput,
        output_model=NotificationSendOutput,
        risk_level=RiskLevel.MEDIUM,
        side_effect_type=SideEffectType.EXTERNAL_WRITE,
        default_timeout_seconds=8.0,
        max_timeout_seconds=15.0,
        # Phase 10 Block 2: the handler no longer makes a synchronous
        # provider call, so ``WRITE_RETRYABLE_CODES`` can no longer actually
        # occur here — but ``max_retries`` also bounds the *cross-call*
        # idempotency-key attempt budget (``tools/execution.py:
        # _resolve_existing``), which still matters: a transient failure in
        # this handler itself (e.g. a DB hiccup) should still leave room for
        # the same logical action to be retried under its existing key,
        # rather than permanently exhausting it on the first failure.
        # Retries against the actual provider now live entirely in the
        # async delivery/attempt state machine (``notifications``), bounded
        # separately by ``Delivery.max_attempts``.
        retry_policy=RetryPolicy(max_retries=2, retryable_error_codes=WRITE_RETRYABLE_CODES),
        idempotency_mode=IdempotencyMode.REQUIRED,
    ),
    handler=_notification_send_handler,
)


ALL_INTEGRATION_TOOLS = (
    CUSTOMER_LOOKUP_TOOL,
    ORDER_LOOKUP_TOOL,
    SHIPMENT_LOOKUP_TOOL,
    PAYMENT_LOOKUP_TOOL,
    PAYMENT_REFUND_TOOL,
    CALENDAR_AVAILABILITY_TOOL,
    CALENDAR_BOOKING_TOOL,
    TICKET_CREATE_TOOL,
    TICKET_UPDATE_TOOL,
    NOTIFICATION_SEND_TOOL,
)


def register_integration_tools(target_registry) -> None:  # noqa: ANN001
    for tool in ALL_INTEGRATION_TOOLS:
        if tool.spec.key not in target_registry:
            target_registry.register(tool)
