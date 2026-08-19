"""Credential encryption at rest (section 14-18, 85-86)."""

from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet

from integrations.crypto import (
    CredentialEncryptionError,
    _multi_fernet,
    decrypt_credentials,
    encrypt_credentials,
)


class TestEncryptDecryptRoundTrip:
    def test_round_trip_recovers_plaintext(self):
        data = {"secret_key": "sk_test_abc123"}
        ciphertext = encrypt_credentials(data)
        assert decrypt_credentials(ciphertext) == data

    def test_ciphertext_differs_from_plaintext(self):
        data = {"secret_key": "sk_test_abc123"}
        ciphertext = encrypt_credentials(data)
        assert "sk_test_abc123" not in ciphertext

    def test_ciphertext_is_not_deterministic(self):
        data = {"secret_key": "sk_test_abc123"}
        assert encrypt_credentials(data) != encrypt_credentials(data)


class TestTamperingAndCorruption:
    def test_tampered_ciphertext_fails_authentication(self):
        ciphertext = encrypt_credentials({"secret_key": "sk_test_abc123"})
        tampered = ciphertext[:-4] + ("A" if ciphertext[-4] != "A" else "B") + ciphertext[-3:]
        with pytest.raises(CredentialEncryptionError):
            decrypt_credentials(tampered)

    def test_corrupt_payload_fails_safely(self):
        with pytest.raises(CredentialEncryptionError):
            decrypt_credentials("not-a-valid-fernet-token")

    def test_empty_ciphertext_fails_safely(self):
        with pytest.raises(CredentialEncryptionError):
            decrypt_credentials("")

    def test_wrong_key_fails_safely(self, settings):
        ciphertext = encrypt_credentials({"secret_key": "sk_test_abc123"})
        settings.INTEGRATIONS_CREDENTIAL_ENCRYPTION_KEYS = [Fernet.generate_key().decode()]
        with pytest.raises(CredentialEncryptionError):
            decrypt_credentials(ciphertext)

    def test_missing_key_configuration_fails_safely(self, settings):
        settings.INTEGRATIONS_CREDENTIAL_ENCRYPTION_KEYS = []
        with pytest.raises(CredentialEncryptionError):
            encrypt_credentials({"secret_key": "x"})

    def test_malformed_key_configuration_fails_safely(self, settings):
        settings.INTEGRATIONS_CREDENTIAL_ENCRYPTION_KEYS = ["not-a-valid-fernet-key"]
        with pytest.raises(CredentialEncryptionError):
            encrypt_credentials({"secret_key": "x"})

    def test_ciphertext_with_invalid_base64_fails_safely(self):
        with pytest.raises(CredentialEncryptionError):
            decrypt_credentials("!!!not-base64-at-all!!!")

    def test_decrypted_payload_that_is_not_a_json_object_fails_safely(self):
        # Bypass encrypt_credentials (which only accepts a dict) to prove
        # decrypt_credentials rejects a syntactically valid but
        # structurally wrong plaintext instead of returning it as-is.
        token = _multi_fernet().encrypt(json.dumps([1, 2, 3]).encode("utf-8"))
        with pytest.raises(CredentialEncryptionError):
            decrypt_credentials(token.decode("ascii"))

    def test_decrypted_payload_that_is_not_valid_json_fails_safely(self):
        token = _multi_fernet().encrypt(b"not json at all")
        with pytest.raises(CredentialEncryptionError):
            decrypt_credentials(token.decode("ascii"))


class TestKeyRotation:
    def test_old_ciphertext_still_decrypts_after_key_rotation(self, settings):
        original_keys = list(settings.INTEGRATIONS_CREDENTIAL_ENCRYPTION_KEYS)
        ciphertext = encrypt_credentials({"secret_key": "sk_test_abc123"})

        new_key = Fernet.generate_key().decode()
        settings.INTEGRATIONS_CREDENTIAL_ENCRYPTION_KEYS = [new_key, *original_keys]

        assert decrypt_credentials(ciphertext) == {"secret_key": "sk_test_abc123"}

    def test_new_encryption_uses_the_first_configured_key(self, settings):
        original_keys = list(settings.INTEGRATIONS_CREDENTIAL_ENCRYPTION_KEYS)
        new_key = Fernet.generate_key().decode()
        settings.INTEGRATIONS_CREDENTIAL_ENCRYPTION_KEYS = [new_key, *original_keys]

        ciphertext = encrypt_credentials({"secret_key": "sk_test_abc123"})

        settings.INTEGRATIONS_CREDENTIAL_ENCRYPTION_KEYS = [new_key]
        assert decrypt_credentials(ciphertext) == {"secret_key": "sk_test_abc123"}
