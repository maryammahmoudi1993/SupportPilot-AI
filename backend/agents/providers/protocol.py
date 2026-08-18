"""The vendor-independent LLM provider contract.

Runtime and service code depends on ``LLMProvider`` only. Concrete adapters
(``agents.providers.fake``, ``agents.providers.openai_adapter``) implement it
without leaking vendor SDK types across the boundary.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .schemas import LLMRequest, LLMResponse


@runtime_checkable
class LLMProvider(Protocol):
    """Structural contract every LLM provider adapter must satisfy."""

    name: str

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Issue one bounded generation call.

        Implementations must raise a subclass of
        ``agents.providers.errors.ProviderError`` for every failure — never a
        raw vendor SDK exception — and must never include the caller's
        credentials or raw vendor payloads in the raised error.
        """
        ...
