"""Customer views.

Thin by design: resolve tenant-scoped objects via ``customers.selectors``,
check a capability-based permission, and delegate every mutation to
``customers.services``.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from workspaces.permissions import IsWorkspaceMember
from workspaces.views import WorkspaceScopedMixin

from . import selectors, services
from .models import Customer
from .permissions import CanWriteCustomers
from .serializers import CustomerSerializer, CustomerWriteSerializer


def _request_id(request) -> str | None:
    return getattr(request, "request_id", None)


def _as_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes"}


class CustomerListCreateView(WorkspaceScopedMixin, generics.ListCreateAPIView):
    """GET: any active member. POST: any non-viewer role."""

    queryset = Customer.objects.none()

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsWorkspaceMember(), CanWriteCustomers()]
        return [IsWorkspaceMember()]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return CustomerWriteSerializer
        return CustomerSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Customer.objects.none()
        params = self.request.query_params
        return selectors.customer_list_for_workspace(
            workspace=self.workspace,
            search=params.get("search"),
            is_active=_as_bool(params.get("is_active")),
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = services.create_customer(
            workspace=self.workspace, data=serializer.validated_data
        )
        return Response(CustomerSerializer(customer).data, status=status.HTTP_201_CREATED)


class CustomerDetailView(WorkspaceScopedMixin, APIView):
    """GET: any active member. PATCH: any non-viewer role."""

    def get_permissions(self):
        if self.request.method in {"PATCH", "PUT"}:
            return [IsWorkspaceMember(), CanWriteCustomers()]
        return [IsWorkspaceMember()]

    @extend_schema(responses=CustomerSerializer)
    def get(self, request, workspace_id, customer_id):
        customer = selectors.customer_get_for_workspace_or_404(
            workspace=self.workspace, customer_id=customer_id
        )
        return Response(CustomerSerializer(customer).data)

    @extend_schema(request=CustomerWriteSerializer, responses=CustomerSerializer)
    def patch(self, request, workspace_id, customer_id):
        customer = selectors.customer_get_for_workspace_or_404(
            workspace=self.workspace, customer_id=customer_id
        )
        serializer = CustomerWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        customer = services.update_customer(
            workspace=self.workspace,
            customer=customer,
            actor=request.user,
            data=serializer.validated_data,
            request_id=_request_id(request),
        )
        return Response(CustomerSerializer(customer).data)
