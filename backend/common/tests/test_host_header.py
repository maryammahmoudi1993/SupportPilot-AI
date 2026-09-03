"""Host header security (Phase 15 checkpoint 4, Part F, section 24).
Django's own ``ALLOWED_HOSTS`` enforcement (``HttpRequest.get_host``,
checked by ``CommonMiddleware``/URL resolution before any view code runs)
is the actual boundary here — these tests prove it is wired up as expected
in this project and that a rejected Host never leaks a stack trace, rather
than reimplementing Host validation."""

from __future__ import annotations

from django.test import Client, override_settings


@override_settings(ALLOWED_HOSTS=["app.supportpilot.example"], DEBUG=False)
def test_valid_host_is_accepted():
    response = Client().get("/health/", HTTP_HOST="app.supportpilot.example")
    assert response.status_code == 200


@override_settings(ALLOWED_HOSTS=["app.supportpilot.example"], DEBUG=False)
def test_unlisted_host_is_safely_rejected_without_a_stack_trace():
    response = Client().get("/health/", HTTP_HOST="attacker.example")
    assert response.status_code == 400
    body = response.content.decode(errors="replace")
    assert "Traceback" not in body
    assert "DisallowedHost" not in body


@override_settings(ALLOWED_HOSTS=["app.supportpilot.example"], DEBUG=False)
def test_host_containing_a_port_is_validated_on_hostname_only():
    """Django's own ``validate_host`` strips a ``:port`` suffix before
    comparing against ``ALLOWED_HOSTS`` (standard, documented behavior —
    the actual listening port is what matters, not what a client claims in
    the header) — an allowed hostname with an arbitrary port is accepted,
    while a *different* hostname is still rejected even with a port
    attached."""
    allowed = Client().get("/health/", HTTP_HOST="app.supportpilot.example:1337")
    assert allowed.status_code == 200

    attacker = Client().get("/health/", HTTP_HOST="attacker.example:1337")
    assert attacker.status_code == 400
    assert "Traceback" not in attacker.content.decode(errors="replace")


@override_settings(ALLOWED_HOSTS=["app.supportpilot.example"], DEBUG=False)
def test_host_header_injection_style_value_is_safely_rejected():
    response = Client().get("/health/", HTTP_HOST="app.supportpilot.example.attacker.example")
    assert response.status_code == 400
    assert "Traceback" not in response.content.decode(errors="replace")
