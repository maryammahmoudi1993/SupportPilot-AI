"""Health URLs."""

from django.urls import path

from .views import HealthCheckView, ReadinessView

app_name = "health"

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health"),
    path("ready/", ReadinessView.as_view(), name="readiness"),
]
