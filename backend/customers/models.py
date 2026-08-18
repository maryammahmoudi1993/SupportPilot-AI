"""Customer domain models.

A ``Customer`` represents an end customer supported by a workspace. It is
the tenant-scoped root that ``conversations`` and ``tickets`` attach to.
"""

from __future__ import annotations

from django.db import models

from common.models import BaseModel


class Customer(BaseModel):
    """An end customer supported by a workspace.

    ``external_id`` exists to support later CRM/helpdesk/e-commerce
    integrations: optional, and unique within a workspace when provided, but
    never globally unique — the same external identifier may legitimately
    exist in two different workspaces.
    """

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="customers"
    )
    external_id = models.CharField(max_length=255, null=True, blank=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    display_name = models.CharField(max_length=300, blank=True)
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=32, null=True, blank=True)
    company = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "external_id"],
                condition=models.Q(external_id__isnull=False),
                name="uniq_customer_workspace_external_id",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "is_active"], name="cust_ws_active_idx"),
            models.Index(fields=["workspace", "created_at"], name="cust_ws_created_idx"),
            models.Index(fields=["workspace", "email"], name="cust_ws_email_idx"),
        ]

    def __str__(self) -> str:
        return self.display_name or self.email or str(self.id)

    def save(self, *args, **kwargs):
        # Well-defined, non-destructive formatting only — never speculative
        # rewriting of what the caller supplied.
        self.first_name = (self.first_name or "").strip()
        self.last_name = (self.last_name or "").strip()
        self.company = (self.company or "").strip()
        self.notes = self.notes or ""
        if self.email:
            self.email = self.email.strip().lower() or None
        if self.phone:
            self.phone = self.phone.strip() or None
        if self.external_id is not None:
            self.external_id = self.external_id.strip() or None
        if self.display_name:
            self.display_name = self.display_name.strip()
        if not self.display_name:
            full_name = " ".join(part for part in [self.first_name, self.last_name] if part)
            self.display_name = full_name or self.email or self.company or ""
        super().save(*args, **kwargs)
