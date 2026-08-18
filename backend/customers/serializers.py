"""Customer serializers.

Serializers validate request shape only. ``workspace`` is never a writable
field — it is always derived server-side from the URL-resolved workspace.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import Customer


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = [
            "id",
            "external_id",
            "first_name",
            "last_name",
            "display_name",
            "email",
            "phone",
            "company",
            "notes",
            "metadata",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "display_name", "created_at", "updated_at"]


class CustomerWriteSerializer(serializers.Serializer):
    external_id = serializers.CharField(max_length=255, required=False, allow_null=True)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    display_name = serializers.CharField(max_length=300, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_null=True)
    phone = serializers.CharField(max_length=32, required=False, allow_null=True, allow_blank=True)
    company = serializers.CharField(max_length=200, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    metadata = serializers.JSONField(required=False)
    is_active = serializers.BooleanField(required=False)
