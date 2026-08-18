"""Test factories for accounts."""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from accounts.models import User

DEFAULT_PASSWORD = "correct-horse-battery-staple"


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.Sequence(lambda n: f"user{n}@example.com")
    first_name = "Test"
    last_name = "User"
    is_active = True
    password = factory.PostGenerationMethodCall("set_password", DEFAULT_PASSWORD)
