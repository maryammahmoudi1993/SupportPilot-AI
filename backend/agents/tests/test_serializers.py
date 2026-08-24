import pytest
from rest_framework.exceptions import ValidationError

from agents.serializers import AgentRunCreateSerializer, _validate_metadata_size


class TestMetadataSizeValidation:
    def test_small_payload_is_accepted(self):
        assert _validate_metadata_size({"a": 1}) is None

    def test_oversized_payload_is_rejected(self):
        with pytest.raises(ValidationError):
            _validate_metadata_size({"blob": "x" * 20000})


class TestAgentRunCreateSerializer:
    def test_requires_agent_version_id(self):
        serializer = AgentRunCreateSerializer(data={})
        assert serializer.is_valid() is False
        assert "agent_version_id" in serializer.errors

    def test_requires_input_message_unless_trigger_message_id_set(self):
        # Phase 9 (section 17, 97): input_message is only required for the
        # manual/API path; an orchestrated run supplies trigger_message_id
        # (+ conversation_id) instead.
        serializer = AgentRunCreateSerializer(
            data={"agent_version_id": "11111111-1111-1111-1111-111111111111"}
        )
        assert serializer.is_valid() is False
        assert "input_message" in serializer.errors

    def test_trigger_message_id_requires_conversation_id(self):
        serializer = AgentRunCreateSerializer(
            data={
                "agent_version_id": "11111111-1111-1111-1111-111111111111",
                "trigger_message_id": "22222222-2222-2222-2222-222222222222",
            }
        )
        assert serializer.is_valid() is False
        assert "conversation_id" in serializer.errors

    def test_trigger_message_id_with_conversation_id_is_valid_without_input_message(self):
        serializer = AgentRunCreateSerializer(
            data={
                "agent_version_id": "11111111-1111-1111-1111-111111111111",
                "conversation_id": "33333333-3333-3333-3333-333333333333",
                "trigger_message_id": "22222222-2222-2222-2222-222222222222",
            }
        )
        assert serializer.is_valid(), serializer.errors

    def test_trigger_defaults_when_omitted(self):
        serializer = AgentRunCreateSerializer(
            data={
                "agent_version_id": "11111111-1111-1111-1111-111111111111",
                "input_message": "hi",
            }
        )
        assert serializer.is_valid(), serializer.errors
        assert "trigger" not in serializer.validated_data or serializer.validated_data.get(
            "trigger"
        ) in {"manual", None}
