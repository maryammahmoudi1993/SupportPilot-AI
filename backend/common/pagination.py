"""Pagination for SupportPilot AI API."""

from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    """Standard pagination for list endpoints."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500
