"""Shared pytest fixtures (Phase 11 Block 2 remediation)."""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from observability import tracing


@pytest.fixture
def traced(settings):
    """Enable tracing and capture every finished span in memory for the
    duration of one test. Uses
    :func:`observability.tracing.use_provider_for_tests` rather than
    OpenTelemetry's own global provider setter, so this is safe to use
    across many tests regardless of run order (see the module docstring of
    ``observability/tracing.py``)."""
    settings.OBSERVABILITY_TRACING_ENABLED = True
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracing.use_provider_for_tests(provider)
    try:
        yield exporter
    finally:
        tracing.use_provider_for_tests(None)
