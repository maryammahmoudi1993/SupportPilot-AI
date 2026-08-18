"""Environment-driven provider selection.

Never hardcodes credentials. The default (and every normal test/CI path) uses
the deterministic fake provider; the real OpenAI adapter is only constructed
when explicitly configured, and a missing/misconfigured real provider fails
with a stable ``ProviderConfigurationError`` rather than booting a broken
client or falling back silently to network calls in a test environment.
"""

from __future__ import annotations

from django.conf import settings

from .errors import ProviderConfigurationError
from .fake import DeterministicFakeLLMProvider
from .protocol import LLMProvider


def get_llm_provider() -> LLMProvider:
    provider_name = getattr(settings, "AGENTS_LLM_PROVIDER", "fake")
    if provider_name == "fake":
        return DeterministicFakeLLMProvider()
    if provider_name == "openai":
        api_key = getattr(settings, "AGENTS_OPENAI_API_KEY", "") or ""
        if not api_key:
            raise ProviderConfigurationError(
                "AGENTS_LLM_PROVIDER=openai requires AGENTS_OPENAI_API_KEY."
            )
        from .openai_adapter import OpenAIProvider

        return OpenAIProvider(
            api_key=api_key, base_url=getattr(settings, "AGENTS_OPENAI_BASE_URL", None) or None
        )
    raise ProviderConfigurationError(f"Unknown AGENTS_LLM_PROVIDER: {provider_name!r}")
