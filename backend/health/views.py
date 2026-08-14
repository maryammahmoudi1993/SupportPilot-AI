"""Liveness and readiness health check views."""

import logging

from django.db import connections
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger("supportpilot")


class HealthStatusSerializer(serializers.Serializer):
    status = serializers.CharField()


class HealthCheckView(APIView):
    """Liveness endpoint: process is up. Does not touch any dependency."""

    permission_classes = [AllowAny]

    @extend_schema(responses=HealthStatusSerializer)
    def get(self, request):
        return Response({"status": "healthy"})


class ReadinessView(APIView):
    """Readiness endpoint: process is able to serve traffic (DB reachable)."""

    permission_classes = [AllowAny]

    @extend_schema(responses=HealthStatusSerializer)
    def get(self, request):
        try:
            connections["default"].ensure_connection()
            return Response({"status": "ready"})
        except Exception:
            # Do not echo the raw exception: it can contain connection
            # strings, hostnames, or credentials.
            logger.exception("readiness_check_failed")
            return Response({"status": "not_ready"}, status=503)
