"""Authentication endpoints: login, refresh, logout, CSRF priming, and the
current-user endpoint.

Refresh and logout authenticate via the HttpOnly refresh cookie rather than
JWT `Authorization` header or a Django session, so DRF's default
CSRF-exemption does not apply automatically — ``enforce_csrf`` is called
explicitly on every state-changing, cookie-authenticated endpoint.
"""

from __future__ import annotations

from django.conf import settings
from django.middleware.csrf import get_token
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from common.csrf import enforce_csrf
from common.schema import AUTHENTICATION_FAILED_EXAMPLE, error_response
from common.throttling import SafeScopedRateThrottle

from .serializers import LoginRequestSerializer, LoginSuccessSerializer, MeSerializer
from .services import (
    authenticate_by_email,
    clear_refresh_cookie,
    issue_tokens_for_user,
    set_refresh_cookie,
)


class LoginView(APIView):
    """Verify email/password and start a session: JSON access token + a
    fresh HttpOnly refresh cookie. Never returns the refresh token in JSON."""

    # Deliberately keep the default authenticators (rather than `[]`): DRF
    # downgrades a 401 AuthenticationFailed to a 403 whenever a view has no
    # authenticator able to supply a `WWW-Authenticate` challenge header, and
    # `authenticate_by_email` raising AuthenticationFailed on bad credentials
    # must surface as 401, per the generic invalid-credentials contract.
    permission_classes = [AllowAny]
    throttle_classes = [SafeScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(
        request=LoginRequestSerializer,
        responses={
            200: LoginSuccessSerializer,
            401: error_response("Invalid credentials.", examples=[AUTHENTICATION_FAILED_EXAMPLE]),
        },
        examples=[
            OpenApiExample(
                "Login request",
                value={"email": "jane@example.com", "password": "correct-horse-battery-staple"},
                request_only=True,
            ),
            OpenApiExample(
                "Login success",
                value={
                    "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.example-access-token",
                    "user": {
                        "id": 42,
                        "email": "jane@example.com",
                        "display_name": "Jane Doe",
                        "workspaces": [
                            {
                                "id": "5c4d0c9e-6c0a-4b0a-9f0e-1234567890ab",
                                "name": "Acme Support",
                                "slug": "acme-support",
                                "role": "support_agent",
                            }
                        ],
                    },
                },
                response_only=True,
                status_codes=["200"],
            ),
        ],
    )
    def post(self, request):
        enforce_csrf(request)
        serializer = LoginRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = authenticate_by_email(
            request=request,
            email=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
        )
        access_token, refresh_token = issue_tokens_for_user(user)

        response = Response({"access": access_token, "user": MeSerializer(user).data})
        set_refresh_cookie(response, refresh_token)
        return response


class TokenRefreshCookieView(APIView):
    """Rotate the refresh token (read from the HttpOnly cookie) and return a
    fresh access token. The previously-used refresh token is blacklisted."""

    # See LoginView for why the default authenticators are kept: it is what
    # lets an invalid/missing refresh token surface as 401, not 403.
    permission_classes = [AllowAny]
    throttle_classes = [SafeScopedRateThrottle]
    throttle_scope = "refresh"

    @extend_schema(
        request=None,
        responses={200: OpenApiResponse(description="New access token issued.")},
    )
    def post(self, request):
        enforce_csrf(request)
        raw_token = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME)
        if not raw_token:
            raise AuthenticationFailed("Refresh token missing.")

        serializer = TokenRefreshSerializer(data={"refresh": raw_token})
        try:
            # TokenRefreshSerializer.validate() constructs RefreshToken(raw)
            # directly and does not itself catch TokenError (raised for
            # malformed/expired/blacklisted/wrong-type tokens) — translate it
            # into a safe, generic 401 rather than letting it surface as an
            # unhandled 500.
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            raise AuthenticationFailed("Invalid or expired refresh token.") from exc

        access_token = serializer.validated_data["access"]
        rotated_refresh_token = serializer.validated_data.get("refresh", raw_token)

        response = Response({"access": access_token})
        set_refresh_cookie(response, rotated_refresh_token)
        return response


class LogoutView(APIView):
    """Revoke the current refresh token and clear its cookie. Idempotent from
    the browser's perspective: a missing or already-invalid token is a safe
    no-op, not an error."""

    permission_classes = [AllowAny]

    @extend_schema(
        request=None,
        responses={204: OpenApiResponse(description="Logged out.")},
    )
    def post(self, request):
        enforce_csrf(request)
        raw_token = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME)
        if raw_token:
            try:
                RefreshToken(raw_token).blacklist()
            except TokenError:
                # Already invalid/expired/blacklisted — logout still succeeds.
                pass

        response = Response(status=204)
        clear_refresh_cookie(response)
        return response


class MeView(APIView):
    """Current authenticated user plus a safe workspace-membership summary."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=MeSerializer)
    def get(self, request):
        return Response(MeSerializer(request.user).data)


class CsrfTokenView(APIView):
    """Prime the CSRF cookie for the browser flow. Call before login/refresh/
    logout so the required CSRF header can be sent on the follow-up request."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(responses={200: OpenApiResponse(description="CSRF cookie set.")})
    def get(self, request):
        get_token(request)
        return Response({"detail": "CSRF cookie set."})
