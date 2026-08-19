"""Application-layer credential encryption at rest (section 14-18, 85-86).

Uses ``cryptography.fernet`` — a vetted authenticated-encryption
construction (AES-128-CBC + HMAC-SHA256, versioned/timestamped framing) —
rather than a hand-rolled cipher mode. ``MultiFernet`` gives us key rotation
for free: new ciphertext always uses the first configured key; decryption
tries every configured key in order, so an old ciphertext keeps decrypting
after a new key is prepended to ``INTEGRATIONS_CREDENTIAL_ENCRYPTION_KEYS``.

Only ``integrations.services`` (and provider adapters it calls into) may
import this module. No view, serializer, or model ``__str__`` decrypts
credentials — see section 16.
"""

from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings


class CredentialEncryptionError(Exception):
    """Corrupt ciphertext, tampered payload, or missing encryption
    configuration. Never leaks the underlying cryptography exception or key
    material (section 138)."""


def _multi_fernet() -> MultiFernet:
    keys: list[str] = list(getattr(settings, "INTEGRATIONS_CREDENTIAL_ENCRYPTION_KEYS", []) or [])
    if not keys:
        raise CredentialEncryptionError("Credential encryption is not configured.")
    try:
        return MultiFernet([Fernet(key.encode() if isinstance(key, str) else key) for key in keys])
    except (ValueError, TypeError) as exc:
        raise CredentialEncryptionError("Credential encryption key is misconfigured.") from exc


def encrypt_credentials(data: dict[str, Any]) -> str:
    """Serialize and encrypt a plaintext credential dict into an opaque,
    storable token. Callers must discard ``data`` as soon as possible after
    calling this (section 16: minimal plaintext lifetime)."""
    plaintext = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    token = _multi_fernet().encrypt(plaintext)
    return token.decode("ascii")


def decrypt_credentials(ciphertext: str) -> dict[str, Any]:
    """Decrypt a stored token back into a plaintext credential dict.

    Any failure — wrong/rotated-out key, tampering, truncation, or a
    non-JSON payload — becomes ``CredentialEncryptionError``, never a raw
    ``cryptography`` exception or partially-decrypted material (section 138).
    """
    if not ciphertext:
        raise CredentialEncryptionError("No credentials are configured.")
    try:
        plaintext = _multi_fernet().decrypt(ciphertext.encode("ascii"))
    except InvalidToken as exc:
        raise CredentialEncryptionError("Stored credentials could not be decrypted.") from exc
    except (
        ValueError,
        TypeError,
    ) as exc:  # pragma: no cover - Fernet normalizes these to InvalidToken
        raise CredentialEncryptionError("Stored credentials are malformed.") from exc
    try:
        decoded = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CredentialEncryptionError("Stored credentials are corrupt.") from exc
    if not isinstance(decoded, dict):
        raise CredentialEncryptionError("Stored credentials are corrupt.")
    return decoded
