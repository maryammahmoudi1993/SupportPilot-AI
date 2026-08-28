"""
Django settings for SupportPilot AI backend.
Environment configuration via django-environ.
"""

import os
from datetime import timedelta
from pathlib import Path

import environ

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    SECRET_KEY=(str, "dev-key-change-in-production"),
    DATABASE_URL=(str, "postgres://postgres:postgres@localhost:5432/supportpilot"),
    REDIS_URL=(str, "redis://localhost:6379/0"),
    CORS_ALLOWED_ORIGINS=(
        list,
        [
            "http://localhost:3000",
            "http://localhost:8000",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:8000",
        ],
    ),
    CSRF_TRUSTED_ORIGINS=(
        list,
        [
            "http://localhost:3000",
            "http://localhost:8000",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:8000",
        ],
    ),
    AUTH_REFRESH_COOKIE_NAME=(str, "sp_refresh_token"),
    AUTH_REFRESH_COOKIE_SECURE=(bool, False),
    AUTH_REFRESH_COOKIE_SAMESITE=(str, "Lax"),
    AUTH_REFRESH_COOKIE_PATH=(str, "/api/v1/auth/"),
    AUTH_REFRESH_COOKIE_MAX_AGE=(int, 60 * 60 * 24 * 7),
    KNOWLEDGE_MAX_UPLOAD_BYTES=(int, 10 * 1024 * 1024),
    KNOWLEDGE_MAX_PDF_PAGES=(int, 100),
    KNOWLEDGE_CHUNK_SIZE=(int, 1200),
    KNOWLEDGE_CHUNK_OVERLAP=(int, 150),
    KNOWLEDGE_MIN_CHUNK_CHARS=(int, 20),
    KNOWLEDGE_DEFAULT_TOP_K=(int, 5),
    KNOWLEDGE_MAX_TOP_K=(int, 20),
    KNOWLEDGE_MAX_QUERY_LENGTH=(int, 2000),
    KNOWLEDGE_INGESTION_MAX_ATTEMPTS=(int, 3),
    AUTH_LOGIN_THROTTLE_RATE=(str, "10/min"),
    AUTH_REFRESH_THROTTLE_RATE=(str, "30/min"),
    # AI provider layer (Phase 5). The default is the deterministic offline
    # provider so the application boots and every normal test/CI path runs
    # without paid credentials. The real provider is strictly opt-in.
    AGENTS_LLM_PROVIDER=(str, "fake"),
    AGENTS_OPENAI_API_KEY=(str, ""),
    AGENTS_OPENAI_BASE_URL=(str, ""),
    AGENTS_CONTEXT_MAX_MESSAGES=(int, 20),
    AGENTS_CONTEXT_MAX_CHARACTERS=(int, 12_000),
    AGENTS_RAG_TOP_K=(int, 5),
    AGENTS_RAG_MAX_CHARACTERS=(int, 8_000),
    AGENTS_TOOL_RESULT_MAX_CHARACTERS=(int, 4_000),
    # Business integrations (Phase 7). Credential encryption always defaults
    # to a fixed development key so the app boots and every normal test/CI
    # path runs without a production secret (mirrors SECRET_KEY's pattern);
    # this default MUST be overridden in any real deployment (section 84).
    # A comma-separated list supports key rotation: the first key is used for
    # new encryption, all keys are tried on decryption (section 85).
    INTEGRATIONS_CREDENTIAL_ENCRYPTION_KEYS=(
        list,
        ["yhZU1ULKEp92EMdgREGFYEePxDsf_ytYwcmbrNOwhdo="],
    ),
    # Real, side-effecting provider adapters (Stripe, Google Calendar, SMTP)
    # are never constructed unless explicitly enabled. Default/CI is always
    # the deterministic fake — this flag exists so a real adapter can never
    # be reached by accident (section 26, 90, 109).
    INTEGRATIONS_LIVE_PROVIDERS_ENABLED=(bool, False),
    INTEGRATIONS_DEFAULT_TIMEOUT_SECONDS=(float, 8.0),
    INTEGRATIONS_MAX_TIMEOUT_SECONDS=(float, 15.0),
    # Bounded scheduling horizon / limits for calendar.create_booking.
    INTEGRATIONS_CALENDAR_MAX_HORIZON_DAYS=(int, 90),
    INTEGRATIONS_CALENDAR_MAX_TITLE_LENGTH=(int, 200),
    # Bounded content limits for notification.send (section 129).
    INTEGRATIONS_NOTIFICATION_MAX_SUBJECT_LENGTH=(int, 200),
    INTEGRATIONS_NOTIFICATION_MAX_BODY_LENGTH=(int, 5000),
    # Deterministic policy engine and human-approval workflow (Phase 8).
    # Approval requests expire in 24h by default (section 43, 65).
    POLICIES_DEFAULT_APPROVAL_TTL_SECONDS=(int, 60 * 60 * 24),
    POLICIES_MAX_RULES_PER_VERSION=(int, 50),
    # $1000.00 — a financial action at/above this amount is escalated one
    # risk tier (section 22).
    POLICIES_RISK_BUMP_FINANCIAL_AMOUNT_MINOR=(int, 100_000),
    # System default refund policy (section 32): auto-allow up to $50.00,
    # require approval up to $500.00, deny above that — USD only.
    POLICIES_DEFAULT_REFUND_AUTO_ALLOW_MAX_MINOR=(int, 5_000),
    POLICIES_DEFAULT_REFUND_APPROVAL_MAX_MINOR=(int, 50_000),
    # Durable delivery foundation (Phase 10 Block 1). Server-owned defaults
    # only — no client, model, or LLM output may raise these (section 13).
    DELIVERY_DEFAULT_MAX_ATTEMPTS=(int, 5),
    DELIVERY_CLAIM_LEASE_SECONDS=(int, 300),
    # Retry/backoff/recovery sweeper (Phase 10 Block 4). Replaces the Block 1
    # fixed retry delay with deterministic bounded exponential backoff
    # (section 4-5) — server-owned only, never client/model/provider input.
    DELIVERY_RETRY_BASE_DELAY_SECONDS=(int, 30),
    DELIVERY_RETRY_MAX_DELAY_SECONDS=(int, 3600),
    # Bounded batch size for the due-work/expired-claim recovery sweepers
    # (section 11) — never an unbounded in-memory load of all due rows.
    DELIVERY_SWEEP_BATCH_SIZE=(int, 100),
    # Celery Beat cadence for both recovery sweeper tasks (section 18) —
    # server-owned and configurable, never sub-second polling. See
    # ``config/celery.py``.
    DELIVERY_SWEEP_INTERVAL_SECONDS=(float, 30.0),
    # Outbound webhooks (Phase 10 Block 3). HTTPS is required in production;
    # plaintext HTTP is a server-owned opt-in for local/dev only (section 19)
    # — never something an endpoint owner's URL can trigger by itself.
    WEBHOOKS_ALLOW_INSECURE_HTTP=(bool, False),
    WEBHOOKS_CONNECT_TIMEOUT_SECONDS=(float, 5.0),
    WEBHOOKS_READ_TIMEOUT_SECONDS=(float, 10.0),
    WEBHOOKS_MAX_URL_LENGTH=(int, 2048),
    # Manual redrive (Phase 10 Block 4, section 31): redriving a terminal
    # webhook delivery grants a bounded number of additional attempts by
    # raising ``max_attempts`` — never resets ``attempt_count`` or erases
    # attempt history. Server-owned only; never client-supplied.
    WEBHOOKS_REDRIVE_ATTEMPT_ALLOWANCE=(int, 3),
)

environ.Env.read_env(os.path.join(BASE_DIR.parent, ".env"))

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env("SECRET_KEY")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env("DEBUG")

ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "django_filters",
    # Local apps
    "common.apps.CommonConfig",
    "accounts.apps.AccountsConfig",
    "workspaces.apps.WorkspacesConfig",
    "customers.apps.CustomersConfig",
    "conversations.apps.ConversationsConfig",
    "tickets.apps.TicketsConfig",
    "knowledge.apps.KnowledgeConfig",
    "agents.apps.AgentsConfig",
    "tools.apps.ToolsConfig",
    "integrations.apps.IntegrationsConfig",
    "policies.apps.PoliciesConfig",
    "approvals.apps.ApprovalsConfig",
    "notifications.apps.NotificationsConfig",
    "webhooks.apps.WebhooksConfig",
    "observability.apps.ObservabilityConfig",
    "evaluations.apps.EvaluationsConfig",
    "audit.apps.AuditConfig",
    "health.apps.HealthConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "common.middleware.RequestIdMiddleware",
    "common.middleware.StructuredLoggingMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database
DATABASES = {
    "default": env.db_url(),
}

# Cache
CACHES = {
    "default": env.cache_url(default="redis://localhost:6379/0"),
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Media files
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Custom user model
AUTH_USER_MODEL = "accounts.User"

# REST Framework
REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "common.pagination.StandardResultsSetPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "common.exceptions.custom_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_THROTTLE_RATES": {
        "login": env("AUTH_LOGIN_THROTTLE_RATE"),
        "refresh": env("AUTH_REFRESH_THROTTLE_RATE"),
    },
}

# drf-spectacular
#
# ``role`` appears on several unrelated serializers (workspace membership,
# conversation/ticket assignee summaries) that all share the same underlying
# ``WorkspaceRole`` choices — pin the generated enum name explicitly so
# schema generation does not have to guess and warn about the collision.
SPECTACULAR_SETTINGS = {
    "ENUM_NAME_OVERRIDES": {
        "WorkspaceRoleEnum": "workspaces.models.WorkspaceRole.choices",
        "PriorityEnum": "tickets.models.TicketPriority.choices",
        "ConversationStatusEnum": "conversations.models.ConversationStatus.choices",
        "TicketStatusEnum": "tickets.models.TicketStatus.choices",
        "KnowledgeSourceTypeEnum": "knowledge.models.KnowledgeSourceType.choices",
        "KnowledgeDocumentStatusEnum": "knowledge.models.KnowledgeDocumentStatus.choices",
        "KnowledgeIngestionStatusEnum": "knowledge.models.KnowledgeIngestionStatus.choices",
        "AgentDefinitionStatusEnum": "agents.models.AgentDefinitionStatus.choices",
        "AgentVersionStatusEnum": "agents.models.AgentVersionStatus.choices",
        "AgentProviderEnum": "agents.models.AgentProvider.choices",
        "AgentRunStatusEnum": "agents.models.AgentRunStatus.choices",
        "AgentRunTriggerEnum": "agents.models.AgentRunTrigger.choices",
        "AgentStepTypeEnum": "agents.models.AgentStepType.choices",
        "AgentStepStatusEnum": "agents.models.AgentStepStatus.choices",
        "IntegrationProviderEnum": "integrations.models.IntegrationProvider.choices",
        "IntegrationEnvironmentEnum": "integrations.models.IntegrationEnvironment.choices",
        "IntegrationConnectionStatusEnum": (
            "integrations.models.IntegrationConnectionStatus.choices"
        ),
        "RiskLevelEnum": "tools.contracts.RiskLevel.choices",
        "SideEffectTypeEnum": "tools.contracts.SideEffectType.choices",
        "PolicyStatusEnum": "policies.models.PolicyStatus.choices",
        "PolicyVersionStatusEnum": "policies.models.PolicyVersionStatus.choices",
        "PolicyEffectEnum": "policies.models.PolicyEffect.choices",
        "ApprovalStatusEnum": "approvals.models.ApprovalStatus.choices",
        "ApprovalDecisionValueEnum": "approvals.models.ApprovalDecisionValue.choices",
        "WebhookEndpointStatusEnum": "webhooks.models.WebhookEndpointStatus.choices",
        "WebhookEventTypeEnum": "webhooks.models.WebhookEventType.choices",
    },
}

# Simple JWT
#
# Access tokens are short-lived and returned in the JSON body for the
# frontend to hold in memory; they never carry authoritative workspace-role
# claims (see workspaces/permissions.py). Refresh tokens are long-lived,
# HttpOnly-cookie-only, rotated on every use, and blacklisted after rotation.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
}

# Auth refresh cookie. Read from settings/environment, never hard-coded at
# the call site. SameSite/Secure/Path are all explicit and testable.
AUTH_REFRESH_COOKIE_NAME = env("AUTH_REFRESH_COOKIE_NAME")
AUTH_REFRESH_COOKIE_SECURE = env("AUTH_REFRESH_COOKIE_SECURE") or not DEBUG
AUTH_REFRESH_COOKIE_SAMESITE = env("AUTH_REFRESH_COOKIE_SAMESITE")
AUTH_REFRESH_COOKIE_PATH = env("AUTH_REFRESH_COOKIE_PATH")
AUTH_REFRESH_COOKIE_MAX_AGE = env("AUTH_REFRESH_COOKIE_MAX_AGE")

# CORS — no wildcard origin; credentials only enabled for explicitly
# configured origins so cross-origin browser refresh cookies work as
# intended and nowhere else.
CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True

# CSRF — required because refresh/logout authenticate via a browser cookie.
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")
CSRF_COOKIE_NAME = "sp_csrftoken"
CSRF_HEADER_NAME = "HTTP_X_CSRFTOKEN"

# Celery
CELERY_BROKER_URL = env("REDIS_URL")
CELERY_RESULT_BACKEND = env("REDIS_URL")
CELERY_ACCEPT_CONTENT = ["application/json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"

# Knowledge ingestion/retrieval. The vector dimension is a persisted schema
# decision: changing it requires a migration and re-indexing existing chunks.
KNOWLEDGE_MAX_UPLOAD_BYTES = env("KNOWLEDGE_MAX_UPLOAD_BYTES")
KNOWLEDGE_MAX_PDF_PAGES = env("KNOWLEDGE_MAX_PDF_PAGES")
KNOWLEDGE_ALLOWED_CONTENT_TYPES = {
    "text/plain": frozenset({".txt"}),
    "text/markdown": frozenset({".md", ".markdown"}),
    "application/pdf": frozenset({".pdf"}),
}
KNOWLEDGE_CHUNK_SIZE = env("KNOWLEDGE_CHUNK_SIZE")
KNOWLEDGE_CHUNK_OVERLAP = env("KNOWLEDGE_CHUNK_OVERLAP")
KNOWLEDGE_MIN_CHUNK_CHARS = env("KNOWLEDGE_MIN_CHUNK_CHARS")
# This is deliberately not runtime-configurable. VectorField dimensions are
# schema state; changing 256 requires a migration plus re-indexing.
KNOWLEDGE_EMBEDDING_DIMENSION = 256
KNOWLEDGE_DEFAULT_TOP_K = env("KNOWLEDGE_DEFAULT_TOP_K")
KNOWLEDGE_MAX_TOP_K = env("KNOWLEDGE_MAX_TOP_K")
KNOWLEDGE_MAX_QUERY_LENGTH = env("KNOWLEDGE_MAX_QUERY_LENGTH")
KNOWLEDGE_INGESTION_MAX_ATTEMPTS = env("KNOWLEDGE_INGESTION_MAX_ATTEMPTS")

if not 0 <= KNOWLEDGE_CHUNK_OVERLAP < KNOWLEDGE_CHUNK_SIZE:
    raise ValueError("KNOWLEDGE_CHUNK_OVERLAP must be >= 0 and smaller than chunk size")

# AI provider layer (Phase 5). Never hardcode credentials; the real adapter
# is only constructed when AGENTS_LLM_PROVIDER=openai and a key is present
# (see agents/providers/config.py).
AGENTS_LLM_PROVIDER = env("AGENTS_LLM_PROVIDER")
AGENTS_OPENAI_API_KEY = env("AGENTS_OPENAI_API_KEY")
AGENTS_OPENAI_BASE_URL = env("AGENTS_OPENAI_BASE_URL")
AGENTS_CONTEXT_MAX_MESSAGES = env("AGENTS_CONTEXT_MAX_MESSAGES")
AGENTS_CONTEXT_MAX_CHARACTERS = env("AGENTS_CONTEXT_MAX_CHARACTERS")
AGENTS_RAG_TOP_K = env("AGENTS_RAG_TOP_K")
AGENTS_RAG_MAX_CHARACTERS = env("AGENTS_RAG_MAX_CHARACTERS")
AGENTS_TOOL_RESULT_MAX_CHARACTERS = env("AGENTS_TOOL_RESULT_MAX_CHARACTERS")

if AGENTS_CONTEXT_MAX_MESSAGES < 1 or AGENTS_CONTEXT_MAX_CHARACTERS < 1:
    raise ValueError("Agent conversation context limits must be positive")
if not 1 <= AGENTS_RAG_TOP_K <= KNOWLEDGE_MAX_TOP_K:
    raise ValueError("AGENTS_RAG_TOP_K must be within the Phase 4 retrieval limit")
if AGENTS_RAG_MAX_CHARACTERS < 1:
    raise ValueError("AGENTS_RAG_MAX_CHARACTERS must be positive")
if AGENTS_TOOL_RESULT_MAX_CHARACTERS < 64:
    raise ValueError("AGENTS_TOOL_RESULT_MAX_CHARACTERS must be at least 64")

# Business integrations (Phase 7). See ``integrations/crypto.py`` and
# ``integrations/providers/factory.py``. Real/live-mode execution is
# strictly opt-in; the default is always the deterministic fake provider
# path, matching the AI provider layer's pattern above.
INTEGRATIONS_CREDENTIAL_ENCRYPTION_KEYS = env("INTEGRATIONS_CREDENTIAL_ENCRYPTION_KEYS")
INTEGRATIONS_LIVE_PROVIDERS_ENABLED = env("INTEGRATIONS_LIVE_PROVIDERS_ENABLED")
INTEGRATIONS_DEFAULT_TIMEOUT_SECONDS = env("INTEGRATIONS_DEFAULT_TIMEOUT_SECONDS")
INTEGRATIONS_MAX_TIMEOUT_SECONDS = env("INTEGRATIONS_MAX_TIMEOUT_SECONDS")
INTEGRATIONS_CALENDAR_MAX_HORIZON_DAYS = env("INTEGRATIONS_CALENDAR_MAX_HORIZON_DAYS")
INTEGRATIONS_CALENDAR_MAX_TITLE_LENGTH = env("INTEGRATIONS_CALENDAR_MAX_TITLE_LENGTH")
INTEGRATIONS_NOTIFICATION_MAX_SUBJECT_LENGTH = env("INTEGRATIONS_NOTIFICATION_MAX_SUBJECT_LENGTH")
INTEGRATIONS_NOTIFICATION_MAX_BODY_LENGTH = env("INTEGRATIONS_NOTIFICATION_MAX_BODY_LENGTH")

# Deterministic policy engine and human-approval workflow (Phase 8). See
# ``docs/architecture/policy-approval-engine.md``. Every value here is a
# server-owned default a workspace policy can only ever be *evaluated
# against*, never a value client input can override (section 6, 79-80).
POLICIES_DEFAULT_APPROVAL_TTL_SECONDS = env("POLICIES_DEFAULT_APPROVAL_TTL_SECONDS")
POLICIES_MAX_RULES_PER_VERSION = env("POLICIES_MAX_RULES_PER_VERSION")
# Dynamic risk adjustment (section 22-23): a financial action at or above
# this amount is escalated by one risk tier regardless of its static base
# risk. Independent of the refund auto-allow/approval thresholds below.
POLICIES_RISK_BUMP_FINANCIAL_AMOUNT_MINOR = env("POLICIES_RISK_BUMP_FINANCIAL_AMOUNT_MINOR")
# The system default refund policy (section 32-34) — USD only; any other
# currency always requires approval under the default policy until a
# workspace configures its own currency-specific rule.
POLICIES_DEFAULT_REFUND_AUTO_ALLOW_MAX_MINOR = env("POLICIES_DEFAULT_REFUND_AUTO_ALLOW_MAX_MINOR")
POLICIES_DEFAULT_REFUND_APPROVAL_MAX_MINOR = env("POLICIES_DEFAULT_REFUND_APPROVAL_MAX_MINOR")

# Durable delivery foundation (Phase 10 Block 1) — see
# ``notifications/models.py`` and ``notifications/services.py``. A worker's
# claim lease and a delivery's default retry budget are both server-owned;
# neither is ever accepted from client, model, or LLM input.
DELIVERY_DEFAULT_MAX_ATTEMPTS = env("DELIVERY_DEFAULT_MAX_ATTEMPTS")
DELIVERY_CLAIM_LEASE_SECONDS = env("DELIVERY_CLAIM_LEASE_SECONDS")

# Retry/backoff/recovery sweeper (Phase 10 Block 4) — see
# ``notifications/backoff.py`` and ``notifications/recovery.py``. Bounded
# deterministic exponential backoff, server-owned only (section 4, 13).
DELIVERY_RETRY_BASE_DELAY_SECONDS = env("DELIVERY_RETRY_BASE_DELAY_SECONDS")
DELIVERY_RETRY_MAX_DELAY_SECONDS = env("DELIVERY_RETRY_MAX_DELAY_SECONDS")
DELIVERY_SWEEP_BATCH_SIZE = env("DELIVERY_SWEEP_BATCH_SIZE")
DELIVERY_SWEEP_INTERVAL_SECONDS = env("DELIVERY_SWEEP_INTERVAL_SECONDS")

if DELIVERY_SWEEP_INTERVAL_SECONDS <= 0:
    raise ValueError("DELIVERY_SWEEP_INTERVAL_SECONDS must be positive")

# Outbound webhooks (Phase 10 Block 3) — see ``webhooks/security.py`` and
# ``webhooks/transport.py``. Every value here is server-owned; an endpoint
# owner's URL/configuration can never widen it (section 19, 28).
WEBHOOKS_ALLOW_INSECURE_HTTP = env("WEBHOOKS_ALLOW_INSECURE_HTTP")
WEBHOOKS_CONNECT_TIMEOUT_SECONDS = env("WEBHOOKS_CONNECT_TIMEOUT_SECONDS")
WEBHOOKS_READ_TIMEOUT_SECONDS = env("WEBHOOKS_READ_TIMEOUT_SECONDS")
WEBHOOKS_MAX_URL_LENGTH = env("WEBHOOKS_MAX_URL_LENGTH")

# Manual redrive (Phase 10 Block 4) — see ``webhooks/services.py``.
WEBHOOKS_REDRIVE_ATTEMPT_ALLOWANCE = env("WEBHOOKS_REDRIVE_ATTEMPT_ALLOWANCE")

# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "json": {
            "()": "common.logging.JsonFormatter",
        },
    },
    "filters": {
        "require_debug_false": {
            "()": "django.utils.log.RequireDebugFalse",
        },
        "require_debug_true": {
            "()": "django.utils.log.RequireDebugTrue",
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "json" if not DEBUG else "verbose",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "supportpilot": {
            "handlers": ["console"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
    },
}

# Security settings for production
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
