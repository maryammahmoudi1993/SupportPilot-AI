"""Phase 14 OpenAPI release-contract tests (Section 9-17, 71).

These are deliberate, targeted contract checks — not a byte-for-byte
snapshot of the whole generated document, which would produce noisy,
meaningless diffs on every unrelated model change.
"""

from __future__ import annotations

from collections import Counter

import pytest
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.validation import validate_schema


@pytest.fixture(scope="module")
def schema():
    generator = SchemaGenerator()
    generator.coerce_path_pk = True
    return generator.get_schema(request=None, public=True)


@pytest.mark.django_db
class TestSchemaGeneration:
    def test_schema_generates_and_validates_without_error(self, schema):
        # Raises if the document is not valid OpenAPI 3 — this is the same
        # check `spectacular --validate` performs.
        validate_schema(schema)

    def test_schema_contains_the_expected_scale_of_operations(self, schema):
        operation_count = sum(
            1
            for methods in schema["paths"].values()
            for method in methods
            if method in ("get", "post", "put", "patch", "delete")
        )
        # A loose floor, not an exact count: guards against a catastrophic
        # generation failure (e.g. most apps silently dropped) without
        # forcing an update on every new endpoint.
        assert operation_count >= 100


@pytest.mark.django_db
class TestOperationIds:
    def test_no_duplicate_operation_ids(self, schema):
        operation_ids = [
            op["operationId"]
            for methods in schema["paths"].values()
            for method, op in methods.items()
            if method in ("get", "post", "put", "patch", "delete") and "operationId" in op
        ]
        duplicates = [op_id for op_id, count in Counter(operation_ids).items() if count > 1]
        assert duplicates == []


@pytest.mark.django_db
class TestEnumCollisions:
    def test_conversation_channel_and_channel_type_enums_stay_distinct(self, schema):
        # Regression: Phase 13 discovered and fixed a real enum-name
        # collision here (ae66def). ConversationChannel (web/chat/email/
        # sms/api) and ChannelType (web_chat/email/generic_webhook) are
        # independently meaningful and must not collapse into one
        # generated schema component.
        schemas = schema["components"]["schemas"]
        assert schemas["ConversationChannelEnum"]["enum"] == [
            "web",
            "chat",
            "email",
            "sms",
            "api",
        ]
        assert schemas["ChannelTypeEnum"]["enum"] == ["web_chat", "email", "generic_webhook"]

    def test_no_enum_schema_carries_conflicting_value_sets(self, schema):
        # If drf-spectacular had collapsed two distinct enums into one
        # generated name, that schema's value set would be a superset
        # mixing both domains. Spot-check a representative sample of
        # status enums stay disjoint from unrelated domains.
        schemas = schema["components"]["schemas"]
        assert schemas["TicketStatusEnum"]["enum"] == [
            "open",
            "in_progress",
            "pending",
            "resolved",
            "closed",
        ]
        assert schemas["ConversationStatusEnum"]["enum"] == ["open", "pending", "closed"]


@pytest.mark.django_db
class TestPublicEndpointSecurityMetadata:
    """Section 11/66: the schema's security declarations must reflect the
    real authentication boundary — never imply a public/signed endpoint
    accepts staff JWT/session credentials it never inspects."""

    @pytest.mark.parametrize(
        "path,method",
        [
            ("/health/", "get"),
            ("/ready/", "get"),
            ("/api/v1/channels/public/inbound/{endpoint_id}/", "post"),
            ("/api/v1/channels/public/webchat/{endpoint_id}/session/", "post"),
            ("/api/v1/channels/public/webchat/session/{session_token}/messages/", "post"),
        ],
    )
    def test_public_endpoint_declares_no_security_scheme(self, schema, path, method):
        operation = schema["paths"][path][method]
        assert operation.get("security") == [{}], (
            f"{method.upper()} {path} must declare an explicit empty security "
            "requirement, not inherit jwtAuth/cookieAuth it never checks."
        )

    def test_ordinary_workspace_endpoint_requires_credentials(self, schema):
        operation = schema["paths"]["/api/v1/workspaces/"]["get"]
        security = operation.get("security")
        assert security is not None
        assert {} not in security
        assert any("jwtAuth" in req for req in security)


@pytest.mark.django_db
class TestSecretSchemaHardGate:
    """Section 13/65: secret/credential fields must never round-trip in a
    read response — only a one-time reveal at creation/rotation, and only
    as an explicitly-named field."""

    @pytest.mark.parametrize(
        "schema_name",
        ["IntegrationConnection", "ChannelEndpoint", "WebhookEndpoint"],
    )
    def test_read_schema_exposes_no_plaintext_or_ciphertext_secret(self, schema, schema_name):
        properties = schema["components"]["schemas"][schema_name].get("properties", {})
        forbidden_markers = ("secret", "credential", "password", "token", "key", "cipher")
        for field_name, field_schema in properties.items():
            lowered = field_name.lower()
            if not any(marker in lowered for marker in forbidden_markers):
                continue
            if field_schema.get("format") == "date-time":
                continue  # e.g. secret_created_at — metadata, not a secret value
            # Only bounded metadata (booleans, versions, timestamps) may
            # exist on the read schema — never a raw string value.
            assert field_schema.get("type") != "string", (
                f"{schema_name}.{field_name} looks like a secret-bearing "
                "field but is typed as a raw string on a read schema."
            )

    def test_write_only_credential_inputs_are_marked_write_only(self, schema):
        properties = schema["components"]["schemas"]["IntegrationConnectionCreate"]["properties"]
        assert properties["credentials"].get("writeOnly") is True


@pytest.mark.django_db
class TestPaginationContract:
    def test_paginated_response_has_the_standard_envelope(self, schema):
        schemas = schema["components"]["schemas"]
        paginated = [name for name in schemas if name.startswith("Paginated")]
        assert paginated, "expected at least one paginated list schema"
        sample = schemas[paginated[0]]
        assert set(sample["required"]) == {"count", "results"}
        assert sample["properties"]["next"]["nullable"] is True
        assert sample["properties"]["previous"]["nullable"] is True
        assert sample["properties"]["results"]["type"] == "array"
