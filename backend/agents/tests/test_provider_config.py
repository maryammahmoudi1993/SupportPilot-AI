import pytest

from agents.providers.config import get_llm_provider
from agents.providers.errors import ProviderConfigurationError
from agents.providers.fake import DeterministicFakeLLMProvider
from agents.providers.openai_adapter import OpenAIProvider


class TestGetLLMProvider:
    def test_defaults_to_fake(self, settings):
        settings.AGENTS_LLM_PROVIDER = "fake"
        assert isinstance(get_llm_provider(), DeterministicFakeLLMProvider)

    def test_openai_without_api_key_raises_configuration_error(self, settings):
        settings.AGENTS_LLM_PROVIDER = "openai"
        settings.AGENTS_OPENAI_API_KEY = ""
        with pytest.raises(ProviderConfigurationError):
            get_llm_provider()

    def test_openai_with_api_key_builds_real_adapter(self, settings):
        settings.AGENTS_LLM_PROVIDER = "openai"
        settings.AGENTS_OPENAI_API_KEY = "sk-configured"
        provider = get_llm_provider()
        assert isinstance(provider, OpenAIProvider)

    def test_unknown_provider_name_raises_configuration_error(self, settings):
        settings.AGENTS_LLM_PROVIDER = "not-a-real-provider"
        with pytest.raises(ProviderConfigurationError):
            get_llm_provider()

    def test_application_boots_without_real_provider_credentials(self, settings):
        # The default startup path never requires paid credentials.
        settings.AGENTS_LLM_PROVIDER = "fake"
        settings.AGENTS_OPENAI_API_KEY = ""
        provider = get_llm_provider()
        assert provider.name == "fake"
