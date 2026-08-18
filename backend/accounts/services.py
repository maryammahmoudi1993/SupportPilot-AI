"""Authentication services: credential verification, JWT issuance, and the
refresh-cookie lifecycle.

All token issuance/validation goes through djangorestframework-simplejwt —
no custom cryptographic token implementation.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import authenticate
from django.http import HttpRequest, HttpResponse
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User


def authenticate_by_email(*, request: HttpRequest, email: str, password: str) -> User:
    """Verify credentials via Django's password-hasher pipeline.

    Deliberately returns the identical generic error for an unknown email, a
    wrong password, or an inactive account — an unauthenticated caller gets
    no signal about which case occurred.
    """
    normalized_email = User.objects.normalize_email((email or "").strip())
    candidate = User.objects.filter(email__iexact=normalized_email).first()
    # Always call authenticate() — even with a synthetic username — so a
    # nonexistent account still runs through Django's password hasher and
    # does not respond measurably faster than a real one.
    username = candidate.username if candidate is not None else normalized_email
    user = authenticate(request=request, username=username, password=password)
    if user is None:
        raise AuthenticationFailed("Invalid email or password.")
    return user


def issue_tokens_for_user(user: User) -> tuple[str, str]:
    """Return ``(access_token, refresh_token)`` as encoded strings."""
    refresh = RefreshToken.for_user(user)
    return str(refresh.access_token), str(refresh)


def set_refresh_cookie(response: HttpResponse, refresh_token: str) -> None:
    response.set_cookie(
        settings.AUTH_REFRESH_COOKIE_NAME,
        refresh_token,
        max_age=settings.AUTH_REFRESH_COOKIE_MAX_AGE,
        secure=settings.AUTH_REFRESH_COOKIE_SECURE,
        httponly=True,
        samesite=settings.AUTH_REFRESH_COOKIE_SAMESITE,
        path=settings.AUTH_REFRESH_COOKIE_PATH,
    )


def clear_refresh_cookie(response: HttpResponse) -> None:
    response.delete_cookie(
        settings.AUTH_REFRESH_COOKIE_NAME,
        path=settings.AUTH_REFRESH_COOKIE_PATH,
        samesite=settings.AUTH_REFRESH_COOKIE_SAMESITE,
    )
