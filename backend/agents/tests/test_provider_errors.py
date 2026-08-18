import pytest

from agents.providers import errors


@pytest.mark.parametrize(
    "error_cls,expected_retryable",
    [
        (errors.ProviderAuthenticationError, False),
        (errors.ProviderRateLimitedError, True),
        (errors.ProviderTimeoutError, True),
        (errors.ProviderTemporarilyUnavailableError, True),
        (errors.ProviderInvalidRequestError, False),
        (errors.ProviderMalformedResponseError, False),
        (errors.ProviderContentRejectedError, False),
        (errors.ProviderConfigurationError, False),
        (errors.ProviderError, False),
    ],
)
class TestProviderErrorTaxonomy:
    def test_retry_classification_is_explicit(self, error_cls, expected_retryable):
        assert error_cls.retryable is expected_retryable

    def test_every_error_has_a_stable_code_and_safe_message(self, error_cls, expected_retryable):
        instance = error_cls()
        assert instance.code
        assert instance.safe_message
        assert str(instance) == instance.safe_message

    def test_custom_message_overrides_default_str_but_not_code(self, error_cls, expected_retryable):
        instance = error_cls("a custom safe message")
        assert str(instance) == "a custom safe message"
        assert instance.code == error_cls.code


def test_error_codes_are_unique_across_the_taxonomy():
    classes = [
        errors.ProviderAuthenticationError,
        errors.ProviderRateLimitedError,
        errors.ProviderTimeoutError,
        errors.ProviderTemporarilyUnavailableError,
        errors.ProviderInvalidRequestError,
        errors.ProviderMalformedResponseError,
        errors.ProviderContentRejectedError,
        errors.ProviderConfigurationError,
        errors.ProviderError,
    ]
    codes = [cls.code for cls in classes]
    assert len(codes) == len(set(codes))
