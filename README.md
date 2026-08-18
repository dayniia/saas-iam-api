# saas-iam-api

> **Multi-tenant Identity & Access Management backend** — JWT auth with refresh-token rotation and reuse detection, organisation isolation, database-driven RBAC, invitation flow, session management, and audit logs.

Built as to demonstrate the kind of auth/authorisation infrastructure that real SaaS products run on. The stack is FastAPI + PostgreSQL + Redis, fully containerised, with an integration test suite covering every security boundary.

---

## Live Demo

```
Base URL : https://saas-iam-api.up.railway.app
Swagger  : https://saas-iam-api.up.railway.app/docs
```

> No sign-up needed to explore — use the Swagger UI to hit every endpoint interactively.

---

## What this demonstrates

| Area | Implementation |
|------|----------------|
| **Authentication** | Argon2id password hashing · JWT access tokens (15 min) · hashed refresh tokens · rotation + family-wide reuse detection |
| **Multi-tenancy** | Every resource scoped by `organization_id` · cross-tenant probes return 404 (not 403) · `X-Org-Id` header must match path |
| **Authorisation** | DB-driven RBAC (`roles` / `permissions` / `role_permissions`) · per-request resolution (no stale token claims) · resource-level ownership on projects |
| **Invitations** | Tokenised invite flow with expiry · email-match enforcement · rate-limited |
| **Session management** | List / revoke individual sessions · family revocation on token reuse |
| **Audit log** | Append-only `audit_logs` table · every sensitive action recorded with JSONB metadata · paginated read endpoint (owner/admin only) |
| **Rate limiting** | Redis sliding-window limiter on `/login`, `/refresh`, `/invites` · fails open if Redis is unavailable |

---

## Stack

| Layer | Technology |
|-------|------------|
| Framework | FastAPI 0.115 |
| Database | PostgreSQL 16 + SQLAlchemy 2.0 (async) + Alembic |
| Auth | Argon2-cffi · PyJWT (HS256) |
| Cache / Rate limit | Redis 7 |
| HTTP client (tests) | HTTPX |
| Containerisation | Docker + Docker Compose |
| Python | 3.12 |

---

## Architecture

```
┌──────────────────────────────────────────┐
│            FastAPI application           │
│                                          │
│  Route handlers  →  Service layer        │
│  /api/v1/auth        auth_service        │
│  /api/v1/orgs        org_service         │
│  /api/v1/projects    project_service     │
│  /api/v1/invites     invitation_service  │
│  /api/v1/sessions    (auth_service)      │
│  /api/v1/audit-logs  audit_service       │
│                                          │
│  FastAPI dependencies (app/core/deps.py) │
│  ├── get_current_user   (JWT → User)     │
│  ├── require_permission (DB RBAC check)  │
│  └── rate_limit         (Redis window)   │
│                                          │
│            SQLAlchemy async              │
│                  │                       │
│          ┌───────┴────────┐              │
│          │  PostgreSQL 16 │              │
│          │  users         │              │
│          │  sessions      │              │
│          │  organizations │              │
│          │  memberships   │              │
│          │  roles/perms   │              │
│          │  projects      │              │
│          │  invitations   │              │
│          │  audit_logs    │              │
│          └────────────────┘              │
│                                          │
│          ┌────────────────┐              │
│          │    Redis 7     │ rate limits  │
│          └────────────────┘              │
└──────────────────────────────────────────┘
```

---

## Security design decisions

**Why 404 instead of 403 for cross-tenant access?**
Returning 403 leaks the fact that the resource exists. The API always returns 404, so an attacker cannot enumerate other organisations' resource IDs.

**Why is the refresh token hashed?**
The raw token is a bearer secret. Storing its SHA-256 digest means a database dump cannot be used to impersonate sessions.

**Why does a replayed refresh token revoke the whole session family?**
If a rotated token is replayed, the token was either stolen or the client has a bug. Revoking the entire `family_id` chain forces re-authentication and alerts the legitimate user.

**Why are roles resolved per-request from the database?**
Encoding roles in the JWT means a membership revocation takes up to 15 min to take effect. Database resolution means it takes effect on the very next request.

---

## Quick start

**Requirement:** Docker Desktop

```bash
git clone https://github.com/YOUR_USERNAME/saas-iam-api.git
cd saas-iam-api

cp .env.example .env
# Open .env and set a real SECRET_KEY:
#   openssl rand -hex 32

docker compose up --build
```

The API starts at **http://localhost:8000**.

| URL | Purpose |
|-----|---------|
| `http://localhost:8000/docs` | Interactive Swagger UI |
| `http://localhost:8000/redoc` | ReDoc documentation |
| `http://localhost:8000/health` | Health check |

### Try the core flow in Swagger

1. `POST /api/v1/auth/signup` — create an account
2. `POST /api/v1/auth/login` — get `access_token` + `refresh_token`
3. Click **Authorize** (top right) → paste the access token
4. `POST /api/v1/orgs` — create an organisation, copy the `id`
5. Set `X-Org-Id` header to that `id`
6. `POST /api/v1/orgs/{id}/invites` — invite another user
7. `GET /api/v1/orgs/{id}/audit-logs` — see every action recorded

---

## Running tests

```bash
# Start infrastructure
docker compose up -d

# Create the test database (one-time)
docker compose exec postgres psql -U tac -c "CREATE DATABASE tac_test;"

# Run the suite
pytest -v --tb=short
```

### Test coverage

| File | What it covers |
|------|----------------|
| `test_auth.py` | Signup, login, refresh rotation, reuse detection, logout, **expired JWT → 401** |
| `test_rbac_permissions.py` | Cross-tenant 404, viewer blocked from write, **member cannot change role → 403** |
| `test_invitations.py` | Invite + accept flow, email mismatch, **expired invite → 422** |
| `test_sessions.py` | List, revoke, **cross-user revoke → 404** |
| `test_audit_logs.py` | Owner reads logs, pagination, **viewer → 403** |

---

## API reference

```
POST   /api/v1/auth/signup
POST   /api/v1/auth/login
POST   /api/v1/auth/refresh
POST   /api/v1/auth/logout
GET    /api/v1/auth/me

POST   /api/v1/orgs
GET    /api/v1/orgs
GET    /api/v1/orgs/{id}

GET    /api/v1/orgs/{id}/members
PATCH  /api/v1/orgs/{id}/members/{uid}
DELETE /api/v1/orgs/{id}/members/{uid}

POST   /api/v1/orgs/{id}/invites
POST   /api/v1/invites/accept

POST   /api/v1/orgs/{id}/projects
GET    /api/v1/orgs/{id}/projects
PATCH  /api/v1/orgs/{id}/projects/{pid}
DELETE /api/v1/orgs/{id}/projects/{pid}

GET    /api/v1/me/sessions
POST   /api/v1/me/sessions/{id}/revoke

GET    /api/v1/orgs/{id}/audit-logs
```

---

## Default roles

| Role | Key permissions |
|------|----------------|
| **owner** | All permissions |
| **admin** | All except `org.delete` |
| **member** | `projects.read/write`, `members.read`, `invites.read` |
| **viewer** | `projects.read`, `members.read` |

Roles and permissions are database records — not hardcoded enums. A new permission is a migration + seed update, no application code change required.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | *(required)* | JWT signing key — `openssl rand -hex 32` |
| `DATABASE_URL` | `postgresql+asyncpg://tac:tac@localhost/tac` | PostgreSQL DSN |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access token TTL |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `30` | Refresh token TTL |
| `DEBUG` | `false` | SQL echo — never enable in production |

---

## Project structure

```
.
├── app/
│   ├── api/v1/        # Route handlers — parse, call service, shape response
│   ├── core/
│   │   ├── deps.py    # get_current_user, require_permission, rate_limit
│   │   └── security.py  # Argon2, JWT, SHA-256 token hashing
│   ├── models/        # SQLAlchemy ORM models
│   ├── schemas/       # Pydantic request / response schemas
│   ├── services/      # All business and security logic
│   └── config.py      # Pydantic Settings (env-driven)
├── alembic/           # Database migrations
├── tests/             # Integration test suite (pytest-asyncio + HTTPX)
├── seed.py            # Inserts system roles and permissions
├── Dockerfile
└── docker-compose.yml
```

---

## Author

**Amsal** · [GitHub](https://github.com/YOUR_USERNAME) · [LinkedIn](https://linkedin.com/in/YOUR_PROFILE)
