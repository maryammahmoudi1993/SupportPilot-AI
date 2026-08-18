"""Customer selector tests: tenant isolation, filtering, ordering."""

import pytest

from customers import selectors
from workspaces.tests.factories import WorkspaceFactory

from .factories import CustomerFactory


@pytest.mark.django_db
class TestCustomerListForWorkspace:
    def test_only_returns_customers_in_the_given_workspace(self):
        workspace_a = WorkspaceFactory()
        workspace_b = WorkspaceFactory()
        in_a = CustomerFactory(workspace=workspace_a)
        CustomerFactory(workspace=workspace_b)

        results = list(selectors.customer_list_for_workspace(workspace=workspace_a))

        assert results == [in_a]

    def test_filters_by_is_active(self):
        workspace = WorkspaceFactory()
        active = CustomerFactory(workspace=workspace, is_active=True)
        CustomerFactory(workspace=workspace, is_active=False)

        results = list(selectors.customer_list_for_workspace(workspace=workspace, is_active=True))

        assert results == [active]

    @pytest.mark.parametrize(
        "search_term",
        ["Jane", "Doe", "jane.match@example.com", "555-0100", "ext-42"],
    )
    def test_search_matches_expected_fields(self, search_term):
        workspace = WorkspaceFactory()
        match = CustomerFactory(
            workspace=workspace,
            first_name="Jane",
            last_name="Doe",
            email="jane.match@example.com",
            phone="555-0100",
            external_id="ext-42",
        )
        CustomerFactory(workspace=workspace, first_name="Other", last_name="Person")

        results = list(
            selectors.customer_list_for_workspace(workspace=workspace, search=search_term)
        )

        assert results == [match]

    def test_orders_by_created_at_descending(self):
        workspace = WorkspaceFactory()
        first = CustomerFactory(workspace=workspace)
        second = CustomerFactory(workspace=workspace)

        results = list(selectors.customer_list_for_workspace(workspace=workspace))

        assert results == [second, first]


@pytest.mark.django_db
class TestCustomerGetForWorkspaceOr404:
    def test_returns_customer_in_workspace(self):
        workspace = WorkspaceFactory()
        customer = CustomerFactory(workspace=workspace)

        found = selectors.customer_get_for_workspace_or_404(
            workspace=workspace, customer_id=customer.id
        )

        assert found == customer

    def test_raises_404_for_customer_in_another_workspace(self):
        from django.http import Http404

        workspace_a = WorkspaceFactory()
        foreign_customer = CustomerFactory(workspace=WorkspaceFactory())

        with pytest.raises(Http404):
            selectors.customer_get_for_workspace_or_404(
                workspace=workspace_a, customer_id=foreign_customer.id
            )
