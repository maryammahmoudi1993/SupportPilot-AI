# SupportPilot AI

An agentic customer-operations platform that resolves support requests by retrieving business context, selecting approved tools, enforcing deterministic policy, executing bounded actions, requesting human approval for risky actions, escalating when uncertain, and preserving structured execution traces and immutable audit history.

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.11+
- Node.js 18+

### Development Setup

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -e ".[dev]"

# Migrations
python manage.py migrate

# Run development server
python manage.py runserver

# Frontend (in another terminal)
cd frontend
npm install
npm run dev
```

### Using Docker Compose

```bash
docker-compose up -d
```

Access:
- API: http://localhost:8000/api/v1/
- Frontend: http://localhost:3000
- Admin: http://localhost:8000/admin/

## Project Structure

```
supportpilot-ai/
├── backend/                 # Django/DRF API
│   ├── config/             # Django project settings
│   ├── common/             # Shared utilities, middleware
│   ├── accounts/           # User authentication
│   ├── workspaces/         # Workspace tenancy
│   ├── customers/          # Customer management
│   ├── conversations/      # Chat/messaging
│   ├── tickets/            # Support tickets
│   ├── knowledge/          # RAG/knowledge base
│   ├── agents/             # Agent runtime
│   ├── tools/              # Tool registry
│   ├── integrations/       # External integrations
│   ├── policies/           # Policy engine
│   ├── approvals/          # Approval workflows
│   ├── notifications/      # Notification delivery
│   ├── observability/      # Logging, traces, metrics
│   ├── evaluations/        # Agent evaluation
│   ├── audit/              # Audit events
│   ├── health/             # Health checks
│   ├── tests/              # Test factories, fixtures
│   ├── manage.py
│   ├── pyproject.toml
│   ├── pytest.ini
│   ├── Dockerfile
│   └── entrypoint.sh
├── frontend/               # React/TypeScript
│   ├── src/
│   ├── public/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── vitest.config.ts
│   ├── Dockerfile
│   └── playwright.config.ts
├── infra/
│   └── nginx.conf
├── docs/
│   ├── architecture/
│   ├── adr/
│   ├── api/
│   ├── deployment/
│   └── security/
├── scripts/
│   ├── seed.sh
│   └── health-check.sh
├── .github/
│   └── workflows/
│       ├── backend-ci.yml
│       └── frontend-ci.yml
├── docker-compose.yml
├── docker-compose.prod.yml
└── README.md
```

## Architecture

See [docs/architecture/README.md](docs/architecture/README.md) for detailed architecture documentation and ADRs.

## Development Guidelines

- **One phase = one branch** using pattern: `backend/feat/scope` or `backend/test/scope`
- **Commits**: Use Conventional Commits with meaningful scopes
- **Tests**: Ship tests with every feature
- **Coverage**: Backend target >=95%, Frontend target >=90%
- **Security**: Server-enforced RBAC, tenant isolation, audit trails

## Testing

### Backend

```bash
cd backend
pytest                    # Run all tests
pytest -v               # Verbose
pytest --cov           # With coverage
pytest -k test_name    # Specific test
```

### Frontend

```bash
cd frontend
npm run test            # Run Vitest
npm run test:e2e       # Run Playwright
npm run test:a11y      # Accessibility checks
```

## API Documentation

OpenAPI schema available at: `http://localhost:8000/api/schema/`

## License

Proprietary - SupportPilot AI
