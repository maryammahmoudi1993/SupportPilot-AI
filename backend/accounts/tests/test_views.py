"""Tests for accounts views: the `me` action and its serializer."""

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.models import User
from accounts.views import UserSerializer, UserViewSet


@pytest.mark.django_db
class TestUserSerializer:
    def test_serializes_expected_fields_only(self):
        user = User.objects.create_user(
            username="jane", email="jane@example.com", password="not-a-real-password"
        )

        data = UserSerializer(user).data

        assert set(data.keys()) == {"id", "email", "first_name", "last_name", "is_active"}
        assert data["email"] == "jane@example.com"


@pytest.mark.django_db
class TestUserViewSetMeAction:
    def test_returns_the_authenticated_user(self):
        user = User.objects.create_user(
            username="jane", email="jane@example.com", password="not-a-real-password"
        )
        request = APIRequestFactory().get("/api/v1/auth/users/me/")
        force_authenticate(request, user=user)

        response = UserViewSet.as_view({"get": "me"})(request)

        assert response.status_code == 200
        assert response.data["email"] == "jane@example.com"

    def test_requires_authentication(self):
        request = APIRequestFactory().get("/api/v1/auth/users/me/")

        response = UserViewSet.as_view({"get": "me"})(request)

        assert response.status_code == 401
