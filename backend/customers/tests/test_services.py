"""Customer service tests: creation, update, and controlled deactivation."""

import pytest

from accounts.tests.factories import UserFactory
from audit.models import AuditEvent
from common.exceptions import ConflictError
from customers import services
from workspaces.tests.factories import WorkspaceFactory

from .factories import CustomerFactory


@pytest.mark.django_db
class TestCreateCustomer:
    def test_creates_customer_in_workspace(self):
        workspace = WorkspaceFactory()
        customer = services.create_customer(
            workspace=workspace, data={"first_name": "Jane", "last_name": "Doe"}
        )
        assert customer.workspace_id == workspace.id

    def test_ignores_unknown_fields(self):
        workspace = WorkspaceFactory()
        customer = services.create_customer(
            workspace=workspace, data={"first_name": "Jane", "workspace": "hijacked"}
        )
        assert customer.workspace_id == workspace.id

    def test_duplicate_external_id_raises_conflict(self):
        workspace = WorkspaceFactory()
        CustomerFactory(workspace=workspace, external_id="dup-1")
        with pytest.raises(ConflictError):
            services.create_customer(workspace=workspace, data={"external_id": "dup-1"})


@pytest.mark.django_db
class TestUpdateCustomer:
    def test_updates_supplied_fields_only(self):
        customer = CustomerFactory(first_name="Jane", last_name="Doe")
        actor = UserFactory()

        updated = services.update_customer(
            workspace=customer.workspace,
            customer=customer,
            actor=actor,
            data={"last_name": "Smith"},
        )

        assert updated.first_name == "Jane"
        assert updated.last_name == "Smith"

    def test_deactivating_records_audit_event(self):
        customer = CustomerFactory(is_active=True)
        actor = UserFactory()

        services.update_customer(
            workspace=customer.workspace,
            customer=customer,
            actor=actor,
            data={"is_active": False},
            request_id="req-1",
        )

        event = AuditEvent.objects.get(target_type="customer", target_id=str(customer.id))
        assert event.action == "customer.deactivated"
        assert event.actor == actor
        assert event.request_id == "req-1"

    def test_reactivating_does_not_record_deactivation_event(self):
        customer = CustomerFactory(is_active=False)
        actor = UserFactory()

        services.update_customer(
            workspace=customer.workspace,
            customer=customer,
            actor=actor,
            data={"is_active": True},
        )

        assert not AuditEvent.objects.filter(
            target_type="customer", target_id=str(customer.id)
        ).exists()

    def test_editing_active_fields_does_not_record_audit(self):
        customer = CustomerFactory(is_active=True)
        actor = UserFactory()

        services.update_customer(
            workspace=customer.workspace,
            customer=customer,
            actor=actor,
            data={"notes": "left a note"},
        )

        assert not AuditEvent.objects.filter(target_type="customer").exists()

    def test_duplicate_external_id_on_update_raises_conflict(self):
        workspace = WorkspaceFactory()
        CustomerFactory(workspace=workspace, external_id="taken")
        other = CustomerFactory(workspace=workspace, external_id="free")
        actor = UserFactory()

        with pytest.raises(ConflictError):
            services.update_customer(
                workspace=workspace,
                customer=other,
                actor=actor,
                data={"external_id": "taken"},
            )


@pytest.mark.django_db
class TestDeactivateCustomer:
    def test_sets_is_active_false_and_records_audit(self):
        customer = CustomerFactory(is_active=True)
        actor = UserFactory()

        deactivated = services.deactivate_customer(
            workspace=customer.workspace, customer=customer, actor=actor
        )

        assert deactivated.is_active is False
        assert AuditEvent.objects.filter(
            action="customer.deactivated", target_id=str(customer.id)
        ).exists()
