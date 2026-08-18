# AGENT.md — Team Access Control API

This document is the single source of truth for building this project. Any agent
(human or AI) working on this codebase should read this fully before writing code,
and should keep it updated as decisions change.

---

## 1. Project Overview

**Name:** Team Access Control API
**Type:** Portfolio project — backend/full-stack skill demonstration
**Core idea:** A small IAM-style backend for a SaaS product. Users sign up, create
an organization, invite teammates, get assigned roles, have their permissions
enforced route-by-route and resource-by-resource, can manage/revoke their own
sessions, and every sensitive action is captured in an audit log.

**What this project is meant to prove to a reviewer:**
1. **Secure authentication** — proper password hashing, JWT access/refresh flow,
   refresh token rotation with reuse detection.
2. **Multi-tenant data modeling** — strict organization-level data isolation.
3. **Authorization** — both RBAC (role → permission) and resource-level ownership
   checks (ABAC-ish), enforced via reusable FastAPI dependencies, not scattered
   `if` statements.
4. **Security & API discipline** — rate limiting, hashed secrets at rest, no
   information leakage across tenants (404 vs 403 discipline).
5. **Testing & documentation** — integration tests for the failure paths that
   actually matter in production IAM systems, and OpenAPI docs generated for free
   by FastAPI but curated (tags, descriptions, examples).

**Non-goals for MVP (explicitly out of scope, listed so scope doesn't creep):**
- Billing/payment integration (only a `billing.read` permission stub, no real billing logic)
- Email delivery (invite tokens are returned/logged, not actually emailed)
- Frontend UI (API only — Swagger UI is the "UI")
- Custom/org-defined roles beyond the 4 system roles (schema supports it, feature is deferred)
- SSO/OAuth login providers

---

## 2. Tech Stack

| Concern              | Choice                                      | Why |
|----------------------|----------------------------------------------|-----|
| Language/Framework   | Python 3.12 + FastAPI                       | Async-native, best-in-class OpenAPI generation |
| ORM                  | SQLAlchemy 2.0 (async)                      | Explicit, mature, works well with async Postgres |
| Migrations           | Alembic                                     | A project with no migration history looks unfinished |
| Database             | PostgreSQL 16                               | Relational integrity matters for IAM data |
| Cache / Rate limit   | Redis                                       | Sliding window / token bucket rate limiting, session/token blacklist |
| Validation           | Pydantic v2                                 | Ships with FastAPI |
| Auth                 | `passlib[argon2]` or `bcrypt`, `python-jose` or `pyjwt` | Password hashing + JWT |
| Testing              | `pytest`, `pytest-asyncio`, `httpx.AsyncClient` | Async-native integration testing |
| Docs                 | FastAPI auto OpenAPI (Swagger UI + ReDoc)   | Curated with tags/descriptions, not left default |
| Containerization     | Docker + docker-compose                     | Postgres + Redis + app, one command to run |
| Dependency mgmt      | `uv` or `poetry`                            | Pick one, be consistent |

---

## 3. Folder Structure

```
team-access-control-api/
├── alembic/
│   ├── versions/
│   └── env.py
├── alembic.ini
├── app/
│   ├── main.py                      # FastAPI() instance, router mounting, middleware
│   ├── config.py                    # Settings via pydantic-settings (.env)
│   ├── database.py                  # async engine, session factory, get_db dependency
│   │
│   ├── models/                      # SQLAlchemy ORM models (mirror schema 1:1)
│   │   ├── user.py
│   │   ├── session.py
│   │   ├── organization.py
│   │   ├── membership.py
│   │   ├── role.py
│   │   ├── permission.py
│   │   ├── project.py
│   │   ├── invitation.py
│   │   └── audit_log.py
│   │
│   ├── schemas/                     # Pydantic request/response models
│   │   ├── auth.py
│   │   ├── organization.py
│   │   ├── membership.py
│   │   ├── invitation.py
│   │   └── audit_log.py
│   │
│   ├── core/
│   │   ├── security.py              # password hashing, JWT encode/decode
│   │   ├── deps.py                  # get_current_user, get_current_membership, require_permission
│   │   └── rate_limit.py            # redis-backed limiter setup
│   │
│   ├── services/                    # business logic — kept OUT of route handlers
│   │   ├── auth_service.py          # signup, login, refresh rotation, reuse detection
│   │   ├── org_service.py           # org create, membership management
│   │   ├── rbac_service.py          # has_permission(), role/permission resolution
│   │   ├── invitation_service.py    # create/accept invite
│   │   └── audit_service.py         # write_audit_log(), query helpers
│   │
│   ├── api/
│   │   └── v1/
│   │       ├── router.py            # aggregates all routers
│   │       ├── auth.py              # /signup /login /logout /refresh
│   │       ├── organizations.py     # /orgs /orgs/{id}
│   │       ├── memberships.py       # /orgs/{id}/members
│   │       ├── invitations.py       # /orgs/{id}/invites, /invites/accept
│   │       ├── sessions.py          # /me/sessions, /me/sessions/{id}/revoke
│   │       ├── projects.py          # example resource w/ ownership checks
│   │       └── audit_logs.py        # /orgs/{id}/audit-logs
│   │
│   └── exceptions.py                # custom exception classes + handlers
│
├── tests/
│   ├── conftest.py                  # test DB fixture, client fixture, factory fixtures
│   ├── test_auth.py
│   ├── test_rbac_permissions.py     # cross-tenant isolation tests live here
│   ├── test_invitations.py
│   └── test_sessions.py
│
├── seed.py                          # seeds system roles + permissions
├── docker-compose.yml               # postgres + redis + app
├── Dockerfile
├── requirements.txt / pyproject.toml
├── README.md
└── AGENT.md                         # this file
```

**Rule:** route handlers only parse the request, call a service function, and
shape the response. All business logic lives in `services/`. This keeps
integration tests fast to write and keeps authorization logic in one place.

---

## 4. Data Model (PostgreSQL)

Core tables: `users`, `sessions`, `organizations`, `org_memberships`, `roles`,
`permissions`, `role_permissions`, `projects`, `invitations`, `audit_logs`.

Key modeling decisions:
- **Multi-tenancy**: every tenant-owned table carries `organization_id` directly
  (no multi-hop joins needed for isolation checks). A user can belong to multiple
  orgs via `org_memberships`; role is resolved per-org, not stored on the user.
- **RBAC is DB-driven**: `roles` / `permissions` / `role_permissions` are real
  tables, not hardcoded enums. 4 system roles (`owner`, `admin`, `member`,
  `viewer`) are seeded via `seed.py`. This allows custom per-org roles later
  without a schema migration.
- **Sessions support refresh token reuse detection**: `sessions.family_id` +
  `parent_id` let us detect when an already-rotated refresh token is replayed,
  and revoke the entire token family when that happens.
- **Audit logs use a JSONB `metadata` column** to stay generic across very
  different event shapes (login has no target; role.changed has old/new role)
  without a wide sparse-column table.

See `schema.sql` (or the Alembic migration history) for full DDL — this file
does not duplicate the DDL to avoid drift between two sources of truth.

---

## 5. Authorization Model

Two layers, always applied together where relevant:

1. **RBAC (route-level)** — `require_permission("projects.write")` dependency
   resolves: JWT → user → membership in `X-Org-Id` → role → permission lookup.
   Returns 403 if the role lacks the permission.
2. **Ownership / resource-level (ABAC-ish)** — for actions scoped to a specific
   resource (e.g. editing *your own* project), an additional dependency checks
   `resource.owner_id == membership.user_id` OR role is `admin`/`owner`.

**Isolation discipline:**
- Cross-tenant access (resource belongs to a different org) → **404**, not 403.
  Never confirm a resource exists in an org the user isn't a member of.
- Insufficient permission within the correct org → **403**.
- JWT carries `user_id` only — **not** role or org. Role is resolved fresh from
  `org_memberships` on every request, so a role change or membership revocation
  takes effect immediately, not at token expiry.

---

## 6. MVP Requirements (Definition of Scope)

- [x] User signup / login / logout
- [x] Password hashing (argon2 or bcrypt)
- [x] JWT access token + refresh token rotation
- [x] Refresh tokens stored as hashes only, with reuse detection
- [x] Organization/workspace creation
- [x] Team membership (many-to-many via `org_memberships`)
- [x] System roles: owner, admin, member, viewer
- [x] DB-driven permission table (`users.read`, `invite`, `projects.write`, ...)
- [x] Route-level permission guards (`require_permission`)
- [x] Resource-level ownership checks (project example)
- [x] Invite teammate with expiring invite token
- [x] Accept invitation flow
- [x] Session list + session revoke
- [x] Audit log for: login, invite created/accepted, role change, permission change
- [x] Rate limiting on auth routes (login, refresh, invite)
- [x] Swagger/OpenAPI docs, curated (tags, summaries, examples)
- [x] Integration tests for auth flows and permission failure cases

**Deferred (explicitly not MVP):** `billing.read` beyond a stub permission,
custom per-org roles, email delivery, frontend.

---

## 7. Build Order (Phases)

Build in this order so there's always something demoable, and so the hardest
invariant (tenant isolation) is proven before more features are layered on top:

1. **Auth core** — signup/login/logout, password hashing, JWT access + refresh
   rotation, session storage.
2. **Multi-tenancy** — org creation, membership, and the cross-tenant isolation
   test written *before* moving on. This is the hardest thing to retrofit later.
3. **RBAC** — roles, permissions, role_permissions, `require_permission` guard.
4. **Invites** — expiring token, accept flow, resource ownership checks
   (projects as the example resource).
5. **Sessions + audit logs** — list/revoke sessions, audit log write path, and
   a queryable/paginated `/audit-logs` endpoint.
6. **Rate limiting + OpenAPI polish + full integration test suite.**

---

## 8. Conventions & Standing Decisions

- **All timestamps** UTC, `TIMESTAMPTZ` in Postgres, ISO 8601 in API responses.
- **All IDs** UUID (`gen_random_uuid()` server-side default).
- **Errors**: use a consistent JSON error shape (`{"detail": "..."}` is FastAPI
  default — keep it, don't invent a custom envelope).
- **Secrets**: never log raw JWTs, refresh tokens, or password hashes. Redact in
  any request/response logging middleware.
- **Migrations**: every schema change goes through Alembic — no hand-edited
  prod schema, ever, even in this portfolio project.
- **Service functions** take a `db: AsyncSession` as first arg and never raise
  `HTTPException` directly — they raise domain exceptions (defined in
  `exceptions.py`) that a FastAPI exception handler translates to HTTP responses.
  This keeps `services/` framework-agnostic and independently testable.
- **Every mutating route that touches a sensitive action must write an audit
  log entry** — this is easy to forget, so it's called out explicitly here as a
  checklist item in PR review, not left to memory.
- **Git commits**: small, one logical change each — this repo's commit history
  is itself part of the portfolio signal.

---

## 9. Definition of Done

A feature/phase is "done" only when all of the following are true:

- [ ] Endpoint(s) implemented and wired through `services/`, not inline in route handlers
- [ ] Alembic migration exists for any schema change, and `alembic upgrade head` runs clean on a fresh DB
- [ ] Pydantic request/response schemas defined (no raw dicts returned)
- [ ] Route-level permission guard applied where the action is sensitive
- [ ] Cross-tenant isolation respected (404 on wrong-org access) if the endpoint touches tenant data
- [ ] Audit log entry written for any sensitive action (login, invite, role/permission change, session revoke)
- [ ] Rate limit applied if the endpoint is auth-related or otherwise abuse-prone
- [ ] At least one happy-path integration test
- [ ] At least one failure-path integration test (wrong role, wrong org, expired token, expired invite, etc.)
- [ ] OpenAPI docs are readable — tags, summary, and description set (not left as FastAPI's function-name default)
- [ ] README updated if the change affects setup, env vars, or how to run the project

**Project-level "done" (MVP complete) additionally requires:**
- [ ] `docker-compose up` brings up Postgres + Redis + app with one command
- [ ] `seed.py` seeds system roles/permissions on a fresh DB
- [ ] Full test suite passes (`pytest`) with no skipped tests in the auth/RBAC files
- [ ] A written test proves org A cannot read/write org B's data even with a valid token
- [ ] A written test proves reused (already-rotated) refresh tokens revoke the session family
- [ ] README includes: setup instructions, architecture overview, and a short "what this project demonstrates" section aimed at a technical reviewer

---

## 10. Open Questions / Decisions Log

Track decisions here as they're made so future-you (or another agent) doesn't
re-litigate settled questions.

| Date | Decision | Rationale |
|------|----------|-----------|
| — | Role stored per-org via `org_memberships`, not in JWT | Immediate revocation without waiting for token expiry |
| — | Cross-tenant access returns 404, not 403 | Avoid confirming resource existence to non-members |
| — | Permissions are DB rows, not a hardcoded enum | Enables future custom roles without migration |
| — | `billing.read` is a stub only | Avoid scope creep — the guard pattern is already proven by `projects.write` |
| 2026-07-17 | Password hashing via `argon2-cffi` (not passlib) | Direct Argon2; avoids passlib maintenance issues |
| 2026-07-17 | JWT via PyJWT | Simple, well-maintained |
| 2026-07-17 | Deps via `requirements.txt` (+ optional Poetry metadata) | Reliable installs; Poetry kept in pyproject for tooling |
| 2026-07-17 | Path `{org_id}` must match `X-Org-Id` header | Prevents confused-deputy cross-org access |

---

## 11. Instructions for an AI Agent Picking Up This Repo

- Read this file in full before writing code.
- Do not deviate from the folder structure in Section 3 without updating this file first.
- Do not skip the Section 9 Definition of Done checklist for any PR-sized change.
- If a requirement is ambiguous, prefer the stricter security interpretation
  (e.g. when in doubt between 403 and leaking info, return 404).
- When adding a new sensitive action, always ask: "does this need an audit log
  entry?" — default to yes.
- Keep `services/` framework-agnostic; if you find yourself importing
  `fastapi` inside `services/`, stop and move that logic to `api/` or `core/deps.py`.
