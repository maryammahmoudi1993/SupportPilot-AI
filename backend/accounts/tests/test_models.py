"""Tests for the accounts.User model."""

import pytest
from django.db.utils import IntegrityError

from accounts.models import User


@pytest.mark.django_db
class TestUserModel:
    def test_string_representation_is_the_email(self):
        user = User.objects.create_user(
            username="jane", email="jane@example.com", password="not-a-real-password"
        )

        assert str(user) == "jane@example.com"

    def test_email_must_be_unique(self):
        User.objects.create_user(
            username="jane", email="jane@example.com", password="not-a-real-password"
        )

        with pytest.raises(IntegrityError):
            User.objects.create_user(
                username="jane2", email="jane@example.com", password="not-a-real-password"
            )
