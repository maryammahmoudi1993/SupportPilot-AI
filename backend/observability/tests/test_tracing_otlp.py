"""Tests for the OTLP exporter wiring (Phase 11 Block 3, sections 8-11,
51)."""

from __future__ import annotations

from opentelemetry.sdk.trace.export import BatchSpanProcessor

from observability import tracing


class TestExporterAttachment:
    def test_no_endpoint_means_no_exporter_attached(self, settings):
        settings.OBSERVABILITY_TRACING_ENABLED = True
        settings.OBSERVABILITY_OTLP_ENDPOINT = ""
        tracing.use_provider_for_tests(None)

        provider = tracing.get_tracer_provider()

        assert provider._active_span_processor._span_processors == ()

    def test_endpoint_configured_attaches_a_batch_span_processor(self, settings):
        settings.OBSERVABILITY_TRACING_ENABLED = True
        settings.OBSERVABILITY_OTLP_ENDPOINT = "http://collector.internal:4318/v1/traces"
        tracing.use_provider_for_tests(None)

        provider = tracing.get_tracer_provider()

        processors = provider._active_span_processor._span_processors
        assert len(processors) == 1
        assert isinstance(processors[0], BatchSpanProcessor)

    def test_malformed_endpoint_does_not_break_provider_construction(self, settings, monkeypatch):
        settings.OBSERVABILITY_TRACING_ENABLED = True
        settings.OBSERVABILITY_OTLP_ENDPOINT = "http://collector.internal:4318/v1/traces"
        tracing.use_provider_for_tests(None)

        def _boom(*args, **kwargs):
            raise ValueError("malformed endpoint")

        monkeypatch.setattr(tracing, "OTLPSpanExporter", _boom)

        provider = tracing.get_tracer_provider()  # must not raise

        assert provider is not None

    def test_business_request_succeeds_with_an_unreachable_collector(self, settings):
        """Section 11: an unreachable collector must never affect the
        business operation. BatchSpanProcessor exports on a background
        thread and swallows exporter errors itself; this proves span
        creation/completion around a configured-but-unreachable endpoint
        still behaves normally from the caller's perspective."""
        settings.OBSERVABILITY_TRACING_ENABLED = True
        settings.OBSERVABILITY_OTLP_ENDPOINT = "http://127.0.0.1:1/v1/traces"  # nothing listens
        tracing.use_provider_for_tests(None)

        with tracing.server_span("HTTP request") as span:
            assert span is not None

    def test_no_endpoint_credential_reaches_logs(self, settings, caplog):
        import logging

        settings.OBSERVABILITY_TRACING_ENABLED = True
        settings.OBSERVABILITY_OTLP_ENDPOINT = (
            "http://user:SUPER_SECRET_DOMAIN_OBSERVABILITY_793214@collector.internal:4318/v1/traces"
        )
        tracing.use_provider_for_tests(None)

        with caplog.at_level(logging.DEBUG):
            tracing.get_tracer_provider()

        for record in caplog.records:
            assert "SUPER_SECRET_DOMAIN_OBSERVABILITY_793214" not in record.getMessage()
