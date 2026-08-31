"""Observability infrastructure routes (Phase 11 Block 1).

Wired directly into ``config/urls.py`` at the top level — outside
``api/v1/`` and outside any workspace scope (section 26: this is
deployment infrastructure, not a tenant API).
"""

from __future__ import annotations

from django.urls import path

from .views import metrics_view

urlpatterns = [
    path("metrics/", metrics_view, name="metrics"),
]
