"""Real, opt-in OpenAI provider adapter.

Disabled unless explicitly configured (``AGENTS_LLM_PROVIDER=openai`` plus a
non-empty ``OPENAI_API_KEY``). Never used by default test/CI paths — see
``agents.providers.config.get_llm_provider``. All vendor SDK exceptions are
caught here and mapped to the normalized ``ProviderError`` taxonomy; no raw
SDK object, header, or credential ever crosses this boundary.
"""

from __future__ import annotations

import time
from typing import Any

from .errors import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderContentRejectedError,
    ProviderError,
    ProviderInvalidRequestError,
    ProviderMalformedResponseError,
    ProviderRateLimitedError,
    ProviderTemporarilyUnavailableError,
    ProviderTimeoutError,
)
from .schemas import LLMRequest, LLMResponse, LLMUsage


class OpenAIProvider:
    """Adapter mapping the typed ``LLMProvider`` contract onto the OpenAI SDK."""

    name = "openai"

    def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
        if not api_key:
            raise ProviderConfigurationError("OPENAI_API_KEY is not configured.")
        self._api_key = api_key
        self._base_url = base_url
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import openai

            self._client = openai.OpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._client

    def generate(self, request: LLMRequest) -> LLMResponse:
        import openai

        client = self._get_client()
        started = time.monotonic()
        try:
            completion = client.chat.completions.create(
                model=request.model,
                messages=[{"role": m.role, "content": m.content} for m in request.messages],
                temperature=request.temperature,
                max_tokens=request.max_output_tokens,
                timeout=request.timeout_seconds,
            )
        except openai.AuthenticationError as exc:
            raise ProviderAuthenticationError() from exc
        except openai.RateLimitError as exc:
            raise ProviderRateLimitedError() from exc
        except openai.APITimeoutError as exc:
            raise ProviderTimeoutError() from exc
        except openai.APIConnectionError as exc:
            raise ProviderTemporarilyUnavailableError() from exc
        except openai.BadRequestError as exc:
            raise ProviderInvalidRequestError() from exc
        except openai.APIStatusError as exc:
            if exc.status_code in (500, 502, 503, 504):
                raise ProviderTemporarilyUnavailableError() from exc
            raise ProviderInvalidRequestError() from exc
        except openai.OpenAIError as exc:
            raise ProviderError() from exc
        except Exception as exc:  # pragma: no cover - defensive: never leak an SDK object
            raise ProviderError() from exc

        latency_ms = int((time.monotonic() - started) * 1000)

        try:
            choice = completion.choices[0]
            text = choice.message.content or ""
            finish_reason = choice.finish_reason or "stop"
            usage = completion.usage
            input_tokens = int(usage.prompt_tokens) if usage else 0
            output_tokens = int(usage.completion_tokens) if usage else 0
            total_tokens = int(usage.total_tokens) if usage else input_tokens + output_tokens
        except (IndexError, AttributeError, TypeError, ValueError) as exc:
            raise ProviderMalformedResponseError() from exc

        if finish_reason == "content_filter":
            raise ProviderContentRejectedError()

        return LLMResponse(
            text=text,
            provider=self.name,
            model=request.model,
            finish_reason=finish_reason,
            usage=LLMUsage(
                input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens
            ),
            latency_ms=latency_ms,
            provider_request_id=getattr(completion, "id", None),
        )
