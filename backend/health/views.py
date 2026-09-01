"""Liveness and readiness health check views."""

import logging

from django.core.cache import cache
from django.db import connections
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger("supportpilot")

# Namespaced, short-lived probe key for the readiness cache round-trip
# (Section 27/3): never a user- or workspace-derived value, and cleaned up
# immediately so it never lingers as stray application data.
_READINESS_CACHE_KEY = "health:readiness-probe"
_READINESS_CACHE_VALUE = "1"
_READINESS_CACHE_TIMEOUT = 5


class HealthStatusSerializer(serializers.Serializer):
    status = serializers.CharField()


class HealthCheckView(APIView):
    """Liveness endpoint: process is up. Does not touch any dependency."""

    permission_classes = [AllowAny]

    @extend_schema(responses=HealthStatusSerializer)
    def get(self, request):
        return Response({"status": "healthy"})


class ReadinessView(APIView):
    """Readiness endpoint: process can serve traffic (DB and cache reachable).

    Only dependencies the web process itself requires for normal request
    handling are checked here — PostgreSQL and the shared Django cache
    (Redis). A Celery worker being unavailable does not make the web
    process unready, so it is deliberately not checked; neither are any
    external SaaS providers (Section 27).
    """

    permission_classes = [AllowAny]

    @extend_schema(responses=HealthStatusSerializer)
    def get(self, request):
        try:
            connections["default"].ensure_connection()
            # Bounded round-trip through the configured cache abstraction —
            # never a raw Redis client of its own (Section 27/3).
            cache.set(
                _READINESS_CACHE_KEY, _READINESS_CACHE_VALUE, timeout=_READINESS_CACHE_TIMEOUT
            )
            cache.get(_READINESS_CACHE_KEY)
            cache.delete(_READINESS_CACHE_KEY)
            return Response({"status": "ready"})
        except Exception:
            # Do not echo the raw exception: it can contain connection
            # strings, hostnames, or credentials — for either dependency.
            logger.exception("readiness_check_failed")
            return Response({"status": "not_ready"}, status=503)
