"""Settings validation tests: catch configuration regressions early."""

from django.conf import settings


class TestCoreSettings:
    def test_custom_user_model_is_configured(self):
        assert settings.AUTH_USER_MODEL == "accounts.User"

    def test_default_auto_field_is_explicit(self):
        assert settings.DEFAULT_AUTO_FIELD == "django.db.models.BigAutoField"

    def test_timezone_aware_datetimes_are_enabled(self):
        assert settings.USE_TZ is True
        assert settings.TIME_ZONE == "UTC"

    def test_all_domain_apps_are_installed(self):
        expected = {
            "common",
            "accounts",
            "workspaces",
            "customers",
            "conversations",
            "tickets",
            "knowledge",
            "agents",
            "tools",
            "integrations",
            "policies",
            "approvals",
            "notifications",
            "observability",
            "evaluations",
            "audit",
            "health",
        }
        installed_local_apps = {app.split(".")[0] for app in settings.INSTALLED_APPS if "." in app}
        assert expected <= installed_local_apps


class TestApiFramework:
    def test_error_envelope_handler_is_wired(self):
        assert (
            settings.REST_FRAMEWORK["EXCEPTION_HANDLER"]
            == "common.exceptions.custom_exception_handler"
        )

    def test_pagination_is_enforced_by_default(self):
        assert settings.REST_FRAMEWORK["DEFAULT_PAGINATION_CLASS"] == (
            "common.pagination.StandardResultsSetPagination"
        )

    def test_default_permission_requires_authentication(self):
        assert settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == [
            "rest_framework.permissions.IsAuthenticated"
        ]


class TestRequestCorrelationMiddleware:
    def test_request_id_middleware_runs_before_structured_logging(self):
        request_id_index = settings.MIDDLEWARE.index("common.middleware.RequestIdMiddleware")
        logging_index = settings.MIDDLEWARE.index("common.middleware.StructuredLoggingMiddleware")

        assert request_id_index < logging_index

    def test_metrics_middleware_runs_after_structured_logging(self):
        logging_index = settings.MIDDLEWARE.index("common.middleware.StructuredLoggingMiddleware")
        metrics_index = settings.MIDDLEWARE.index("observability.middleware.MetricsMiddleware")

        assert logging_index < metrics_index


class TestAgentContextSettings:
    def test_conversation_and_rag_limits_are_positive_and_phase4_bounded(self):
        assert settings.AGENTS_CONTEXT_MAX_MESSAGES >= 1
        assert settings.AGENTS_CONTEXT_MAX_CHARACTERS >= 1
        assert 1 <= settings.AGENTS_RAG_TOP_K <= settings.KNOWLEDGE_MAX_TOP_K
        assert settings.AGENTS_RAG_MAX_CHARACTERS >= 1


class TestDeliverySweepInterval:
    def test_sweep_interval_default_is_positive_and_thirty_seconds(self):
        assert settings.DELIVERY_SWEEP_INTERVAL_SECONDS > 0
        assert settings.DELIVERY_SWEEP_INTERVAL_SECONDS == 30.0


class TestCors:
    def test_cors_does_not_allow_all_origins(self):
        assert getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False) is not True

    def test_cors_allowed_origins_is_an_explicit_list(self):
        assert isinstance(settings.CORS_ALLOWED_ORIGINS, list)
        assert "*" not in settings.CORS_ALLOWED_ORIGINS
