"""Approval-domain test factories.

``pending_refund_approval`` builds a *real*, end-to-end pending
``ApprovalRequest`` by actually running ``payment.refund`` through
``execute_tool`` at an amount above the auto-allow threshold — rather than
hand-constructing model rows — so approval-lifecycle tests exercise the same
gate the production code path uses.
"""

from __future__ import annotations

from datetime import UTC, datetime

from customers.tests.factories import CustomerFactory
from integrations.models import IntegrationProvider
from integrations.providers.base import NormalizedPayment
from integrations.providers.fakes import FakePaymentProvider
from integrations.tests.factories import IntegrationConnectionFactory, bind_tool, running_run
from tools.errors import ToolError
from tools.execution import execute_tool

from ..models import ApprovalRequest


def pending_refund_approval(
    monkeypatch, *, amount_minor=10000, currency="usd", idempotency_key=None, created_by=None
):
    run = running_run(created_by=created_by)
    bind_tool(run, "payment.refund")
    IntegrationConnectionFactory(workspace=run.workspace, provider=IntegrationProvider.STRIPE)
    fake = FakePaymentProvider(
        payments={
            "pi_1": NormalizedPayment(
                payment_id="pi_1",
                external_payment_id="pi_1",
                status="succeeded",
                amount_minor=100000,
                currency="USD",
                created_at=datetime(2024, 1, 1, tzinfo=UTC),
                refunded_amount_minor=0,
            )
        }
    )
    monkeypatch.setattr("integrations.services.get_payment_provider", lambda provider: fake)
    try:
        execute_tool(
            agent_run=run,
            tool_key="payment.refund",
            arguments={
                "payment_reference": "pi_1",
                "amount_minor": amount_minor,
                "currency": currency,
            },
            idempotency_key=idempotency_key,
        )
    except ToolError:
        pass  # expected: approval_required
    approval = ApprovalRequest.objects.get(tool_execution__agent_run=run)
    return run, approval, fake


def pending_booking_approval(monkeypatch, *, customer=None):
    from datetime import timedelta

    from django.utils import timezone

    from integrations.providers.fakes import FakeCalendarProvider

    run = running_run()
    bind_tool(run, "calendar.create_booking")
    IntegrationConnectionFactory(
        workspace=run.workspace, provider=IntegrationProvider.GOOGLE_CALENDAR
    )
    fake = FakeCalendarProvider()
    monkeypatch.setattr("integrations.services.get_calendar_provider", lambda provider: fake)
    customer = customer or CustomerFactory(workspace=run.workspace, email="a@example.com")
    start = timezone.now() + timedelta(hours=2)
    end = start + timedelta(minutes=30)
    arguments = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "title": "Onboarding call",
        "customer_id": str(customer.id),
    }
    try:
        execute_tool(agent_run=run, tool_key="calendar.create_booking", arguments=arguments)
    except ToolError:
        pass
    approval = ApprovalRequest.objects.get(tool_execution__agent_run=run)
    return run, approval, fake, arguments
