"""Real OpenAI adapter tests. The network boundary (the SDK client) is
mocked; the internal runtime implementation is not. No test in this module
performs a real HTTP request."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import openai
import pytest

from agents.providers.errors import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderContentRejectedError,
    ProviderInvalidRequestError,
    ProviderMalformedResponseError,
    ProviderRateLimitedError,
    ProviderTemporarilyUnavailableError,
    ProviderTimeoutError,
)
from agents.providers.openai_adapter import OpenAIProvider
from agents.providers.schemas import LLMMessage, LLMRequest


def _request():
    return LLMRequest(messages=(LLMMessage(role="user", content="hi"),), model="gpt-test")


def _fake_request():
    return httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def _completion(text="hello there", finish_reason="stop", usage=(10, 5, 15)):
    return SimpleNamespace(
        id="cmpl-123",
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish_reason)
        ],
        usage=SimpleNamespace(
            prompt_tokens=usage[0], completion_tokens=usage[1], total_tokens=usage[2]
        ),
    )


def _provider_with_client(client):
    provider = OpenAIProvider(api_key="sk-test")
    provider._client = client
    return provider


class TestOpenAIProviderDisabledByDefault:
    def test_missing_api_key_raises_configuration_error(self):
        with pytest.raises(ProviderConfigurationError):
            OpenAIProvider(api_key="")

    def test_real_adapter_is_not_the_default_get_llm_provider(self, settings):
        from agents.providers.config import get_llm_provider
        from agents.providers.fake import DeterministicFakeLLMProvider

        settings.AGENTS_LLM_PROVIDER = "fake"
        assert isinstance(get_llm_provider(), DeterministicFakeLLMProvider)


class TestOpenAIProviderSuccess:
    def test_successful_response_is_normalized(self):
        client = MagicMock()
        client.chat.completions.create.return_value = _completion()
        provider = _provider_with_client(client)
        response = provider.generate(_request())
        assert response.text == "hello there"
        assert response.provider == "openai"
        assert response.usage.total_tokens == 15
        assert response.provider_request_id == "cmpl-123"

    def test_content_filter_finish_reason_is_content_rejected(self):
        client = MagicMock()
        client.chat.completions.create.return_value = _completion(finish_reason="content_filter")
        provider = _provider_with_client(client)
        with pytest.raises(ProviderContentRejectedError):
            provider.generate(_request())

    def test_malformed_response_missing_choices_is_normalized(self):
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(choices=[], usage=None)
        provider = _provider_with_client(client)
        with pytest.raises(ProviderMalformedResponseError):
            provider.generate(_request())


class TestOpenAIProviderErrorMapping:
    def test_authentication_error(self):
        client = MagicMock()
        resp = httpx.Response(401, request=_fake_request(), json={})
        client.chat.completions.create.side_effect = openai.AuthenticationError(
            "bad key", response=resp, body=None
        )
        with pytest.raises(ProviderAuthenticationError):
            _provider_with_client(client).generate(_request())

    def test_rate_limited(self):
        client = MagicMock()
        resp = httpx.Response(429, request=_fake_request(), json={})
        client.chat.completions.create.side_effect = openai.RateLimitError(
            "slow down", response=resp, body=None
        )
        with pytest.raises(ProviderRateLimitedError):
            _provider_with_client(client).generate(_request())

    def test_timeout(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = openai.APITimeoutError(request=_fake_request())
        with pytest.raises(ProviderTimeoutError):
            _provider_with_client(client).generate(_request())

    def test_connection_error_is_temporarily_unavailable(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = openai.APIConnectionError(
            request=_fake_request()
        )
        with pytest.raises(ProviderTemporarilyUnavailableError):
            _provider_with_client(client).generate(_request())

    def test_bad_request_is_invalid_request(self):
        client = MagicMock()
        resp = httpx.Response(400, request=_fake_request(), json={})
        client.chat.completions.create.side_effect = openai.BadRequestError(
            "invalid", response=resp, body=None
        )
        with pytest.raises(ProviderInvalidRequestError):
            _provider_with_client(client).generate(_request())

    def test_5xx_status_error_is_temporarily_unavailable(self):
        client = MagicMock()
        resp = httpx.Response(503, request=_fake_request(), json={})
        client.chat.completions.create.side_effect = openai.APIStatusError(
            "unavailable", response=resp, body=None
        )
        with pytest.raises(ProviderTemporarilyUnavailableError):
            _provider_with_client(client).generate(_request())

    def test_unexpected_exception_never_leaks_raw_sdk_object(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("secret internal detail")
        with pytest.raises(Exception) as excinfo:
            _provider_with_client(client).generate(_request())
        # The normalized error message must never be the raw exception text.
        assert "secret internal detail" not in str(excinfo.value)
