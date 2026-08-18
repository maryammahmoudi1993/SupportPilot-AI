"""Customer model tests: creation, normalization, and tenancy invariants."""

import pytest
from django.db import IntegrityError

from customers.models import Customer
from workspaces.tests.factories import WorkspaceFactory

from .factories import CustomerFactory


@pytest.mark.django_db
class TestCustomerCreation:
    def test_creates_customer_with_defaults(self):
        customer = CustomerFactory()
        assert customer.is_active is True
        assert customer.external_id is None

    def test_belongs_to_workspace(self):
        workspace = WorkspaceFactory()
        customer = CustomerFactory(workspace=workspace)
        assert customer.workspace_id == workspace.id


@pytest.mark.django_db
class TestCustomerNormalization:
    def test_trims_whitespace_on_names_and_company(self):
        customer = CustomerFactory(first_name="  Jane  ", last_name="  Doe  ", company="  Acme  ")
        assert customer.first_name == "Jane"
        assert customer.last_name == "Doe"
        assert customer.company == "Acme"

    def test_normalizes_email_to_lowercase(self):
        customer = CustomerFactory(email="  Jane.Doe@Example.COM  ")
        assert customer.email == "jane.doe@example.com"

    def test_blank_external_id_normalizes_to_none(self):
        customer = CustomerFactory(external_id="   ")
        assert customer.external_id is None

    def test_derives_display_name_when_not_supplied(self):
        customer = CustomerFactory(first_name="Jane", last_name="Doe", display_name="")
        assert customer.display_name == "Jane Doe"

    def test_explicit_display_name_is_preserved(self):
        customer = CustomerFactory(display_name="  Preferred Name  ")
        assert customer.display_name == "Preferred Name"

    def test_falls_back_to_email_when_no_name_available(self):
        customer = CustomerFactory(
            first_name="", last_name="", display_name="", email="only@example.com"
        )
        assert customer.display_name == "only@example.com"


@pytest.mark.django_db
class TestCustomerExternalIdUniqueness:
    def test_optional_external_id_allows_multiple_null_values(self):
        workspace = WorkspaceFactory()
        CustomerFactory(workspace=workspace, external_id=None)
        CustomerFactory(workspace=workspace, external_id=None)
        assert Customer.objects.filter(workspace=workspace, external_id=None).count() == 2

    def test_duplicate_external_id_in_same_workspace_is_rejected(self):
        workspace = WorkspaceFactory()
        CustomerFactory(workspace=workspace, external_id="shopify-123")
        with pytest.raises(IntegrityError):
            CustomerFactory(workspace=workspace, external_id="shopify-123")

    def test_same_external_id_allowed_across_different_workspaces(self):
        workspace_a = WorkspaceFactory()
        workspace_b = WorkspaceFactory()
        CustomerFactory(workspace=workspace_a, external_id="shopify-123")
        # Must not raise.
        customer_b = CustomerFactory(workspace=workspace_b, external_id="shopify-123")
        assert customer_b.external_id == "shopify-123"


@pytest.mark.django_db
class TestCustomerStringRepresentation:
    def test_str_uses_display_name(self):
        customer = CustomerFactory(display_name="Preferred Name")
        assert str(customer) == "Preferred Name"


@pytest.mark.django_db
class TestCustomerActiveState:
    def test_defaults_to_active(self):
        assert CustomerFactory().is_active is True

    def test_can_be_deactivated(self):
        customer = CustomerFactory()
        customer.is_active = False
        customer.save(update_fields=["is_active"])
        customer.refresh_from_db()
        assert customer.is_active is False
