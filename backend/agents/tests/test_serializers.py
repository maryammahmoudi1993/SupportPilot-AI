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
    def test_requires_agent_version_id_and_input_message(self):
        serializer = AgentRunCreateSerializer(data={})
        assert serializer.is_valid() is False
        assert "agent_version_id" in serializer.errors
        assert "input_message" in serializer.errors

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
