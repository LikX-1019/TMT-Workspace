# Security Design

## Security Principles

1. Identity, action permission, workspace access, and data scope are all verified on the backend.
2. Fail closed when required context is missing or invalid.
3. Never expose secrets, tokens, stack traces, internal SQL, or unrestricted enumeration errors.
4. Prefer maintained security libraries over custom cryptographic code.
5. Record evidence for sensitive administrative actions.

## Authentication

Implemented in Phase 1B: local employee accounts authenticate with username/password through `POST /api/v1/auth/login`. Phase 1A creates employee identity only; credentials live in `local_credentials`, kept separate from `users` by design. The architecture reserves an authentication-provider boundary for future enterprise WeChat, Feishu, LDAP, or OIDC integration, but no provider becomes a core dependency.

Implemented login behavior:

- constant-time password verification through `pwdlib` (Argon2id), including a dummy verification against a fixed hash when the account or credential does not exist;
- generic failure message (`Incorrect username or password.`) that does not reveal whether the username or password was wrong;
- login attempt evidence in `login_logs` (result plus `failure_reason` such as `bad_password`, `user_disabled`, `user_resigned`, `user_deleted`, `missing_credential`);
- brute-force throttling in Redis by target username and by client IP (default 10 failures / 300 seconds, configurable through `TMT_LOGIN_MAX_ATTEMPTS` / `TMT_LOGIN_WINDOW_SECONDS`); a locked context returns `429 RATE_LIMITED` even for the correct password, and a successful login clears both counters;
- locked/disabled/resigned/soft-deleted account rejection; `on_leave` employees may still authenticate;
- successful login updates `last_login_at` and writes `login_logs`.

Credential bootstrap for the first account is an operator action, not an HTTP route: `python -m app.cli create-local-credential --username <name>` (password prompt, never an argument).

## Password Policy

Implemented policy (`app/core/security.py`):

- minimum 12 characters;
- rejects exact username, employee number, or email (case-insensitive);
- hashing uses Argon2id through `pwdlib`; verification transparently upgrades legacy-parameter hashes (`check_needs_rehash`) on successful login;
- failure raises `PASSWORD_POLICY_VIOLATED` (422) without echoing which rule matched.

Administrator reset flows and reuse restrictions are future work. Passwords are never recoverable or logged.

## Token Architecture

Implemented in Phase 1B.

Access tokens:

- 30 minutes (default; `TMT_ACCESS_TOKEN_TTL_MINUTES`), HS256 via PyJWT;
- claims are exactly `sub` (user id), `typ=access`, `sid` (session id), `iat`, `exp`, `jti` — no PII, no permission snapshots;
- held in frontend runtime memory only; never written to `localStorage`/`sessionStorage` and never returned in the refresh response body beyond the standard `access_token` field;
- every protected request re-checks account and session state server-side (`/auth/me` validates state on each call; Redis revoked-session markers kill live sessions immediately on logout/reuse detection).

Refresh tokens:

- opaque 384-bit random values (`secrets.token_urlsafe(48)`); browsers only ever hold them in an `HttpOnly` cookie and the database only stores a SHA-256 lookup hash (`refresh_tokens.token_hash`, unique);
- SHA-256 is deliberate: refresh tokens are 384-bit random values (no low-entropy human secrets), so a fast lookup hash plus server-side rotation/state provides the protection Argon2 would, without adding latency to every refresh;
- rotated on every use inside one PostgreSQL transaction with `SELECT ... FOR UPDATE` on the token row, recording lineage via `replaced_by_id`;
- reuse of any rotated/revoked token revokes the entire `session_id` family and marks the session revoked in Redis; the accepted tradeoff is that a delayed retry of an already-rotated cookie also ends the session;
- revoked at logout, reuse detection, administrator disable, or resignation.

Implemented browser flow:

1. `POST /auth/login` returns `access_token`, `token_type`, `expires_in` in the body and sets the refresh cookie;
2. client sends `Authorization: Bearer <access-token>`;
3. dependencies validate signature, expiry, token type, active account, and Redis revoked-session state;
4. `POST /auth/refresh` authenticates from the cookie, rotates it, and issues a new access token;
5. reuse or logout revokes the token family and the session.

Implemented cookie contract:

- name `tmt_refresh_token`, path `/api/v1/auth` (only auth endpoints receive it);
- `HttpOnly`, `SameSite=Lax`, `Secure` forced on in production (`refresh_cookie_secure` cannot be false in production);
- lifetime equals the refresh token TTL (default 14 days);
- CSRF posture: `SameSite=Lax` blocks cross-site POST navigation cookies, and `/auth/refresh` and `/auth/logout` additionally validate the `Origin` header against `TMT_CORS_ORIGINS` when a browser sends one; non-browser clients may omit it.

Access-token persistence is not approved. A page reload restores authentication through `POST /auth/refresh`, never by reading a token from browser storage.

Token algorithm/configuration comes from settings. Secrets are never committed.

## RBAC Enforcement

Every protected API uses reusable dependencies:

```text
get_current_user
require_permissions("system:user:create")
require_workspace_access(workspace)
resolve_data_scope(...)
```

Backend checks are mandatory even if the frontend hides a route/button. Permission resolution uses the active roles and permissions from the database or a correctly invalidated cache. A disabled account or deleted role must not retain access through stale UI state.

### Phase 2B implementation state (enforcement)

- `require_permission(...)` (`app/modules/rbac/dependencies.py`) is the single authorization gate. It depends on `get_current_user`, so unauthenticated requests fail with 401 before any permission logic; only authenticated-but-unauthorized requests get 403. The dependency never catches or rewrites authentication errors.
- `AuthorizationContext` resolves roles + effective permissions once per request via `Depends` caching. It is request-scoped reuse only — explicitly not a Redis/cross-request permission cache, so grant/role/permission changes take effect on the next request.
- Fail-fast catalog validation: `require_permission` rejects unknown codes with `ValueError` at dependency-construction time (route import), keeping typos out of production.
- Denials raise `AuthorizationError` (403, `AUTHORIZATION_FAILED`, empty `details`); the required permission code is logged (user_id + code + route) but never returned to the client.
- No bypass was added: no `username == "admin"`, no user-id checks, no `is_superuser` flag. `super_admin` still flows exclusively through `AuthorizationService` union resolution.

### Phase 2A implementation state

- `get_current_user` still answers authentication only; permission gating lives in the separate `require_permission` dependency.
- `AuthorizationService` (`app/modules/rbac/service.py`) resolves roles and effective permission codes: union of active grants → active roles → active permissions, deduplicated, one joined query, no cache.
- **Super admin strategy**: `super_admin` is a normal system role granted only through `user_roles`. If a user holds it, effective permissions expand dynamically to every active permission code. Rationale: no username/id bypass anywhere (a user named `admin` has zero permissions without grants), new catalog permissions are covered without rewriting assignment rows, and the expansion predicate is directly testable. The resolver checks `role.is_system and role.code == "super_admin"` — nothing else, no special cases.
- System roles (`super_admin`, `system_admin`, `security_auditor`) are seeded by `python -m app.cli sync-permissions`, are protected from disable/delete through `RoleService`, and cannot be assigned while inactive.
- Permission codes are a code-owned catalog (`app/modules/rbac/catalog.py`): grammar `<namespace>:<resource>:<action>`, lowercase, no entity IDs, action-kind only in Phase 2A. Sync is an explicit operator command with `--dry-run`; removed codes are disabled and reported stale, never deleted.
- **No negative permissions**: Phase 2A has grant-only semantics — no deny codes, no precedence rules, no user-direct permission overrides.
- **No permission cache yet**: resolution reads PostgreSQL per request until profiling justifies a cache with its invalidation contract.
- Data scope is stored on roles (`data_scope_type`) but unenforced; `custom` scope's department table is deferred (Phase 3.5). Workspace authorization is Phase 3.

## Data Scope Enforcement

See [DATA_SCOPE_DESIGN.md](DATA_SCOPE_DESIGN.md). Security-critical requirements:

- repositories apply explicit row predicates;
- mutation authorization uses the same predicate as read authorization;
- out-of-scope resources normally return `404`;
- missing scope context fails closed.

## IDOR Prevention

Every object-bearing endpoint must answer:

1. What workspace owns the object?
2. Which department/user owner governs scope?
3. Can the authenticated role see this object class?
4. Can it perform this action?
5. Is the referenced object logically active?

Object IDs are not secrets. Sequential/guessable IDs increase risk and are one reason UUIDs are used for platform entities, but UUIDs alone are not authorization.

## Input And Content Security

- Validate all request data with typed Pydantic models.
- Use SQLAlchemy bound expressions; string-concatenated SQL is prohibited.
- Render announcement content only after an explicit sanitization policy exists.
- Store file uploads outside executable web paths and validate type, size, content, and ownership before adding upload support.
- Encode output according to client context; API JSON encoding is not a substitute for client-side safe rendering.

## Rate Limiting And Brute Force

Redis is used for shared counters because API replicas need consistent limits. Implemented keys:

- `auth:login:user:<sha256(username)>` and `auth:login:ip:<client-ip>` counters with a sliding window equal to `TMT_LOGIN_WINDOW_SECONDS`;
- `auth:revoked-session:<sid>` markers (TTL = access token remaining lifetime) so logout and reuse detection kill live access tokens immediately.

Counters are per normalized username and per IP independently; a successful login clears both. Responses stay generic so throttling does not leak account existence.

## CORS

Production origins are explicit. Do not combine `allow_credentials=True` with a wildcard origin. Default local CORS allows the development frontend origin only. New external integrations receive explicit clients/credentials rather than broad browser CORS access.

## Headers And Transport

Production deployment must use HTTPS and a reverse proxy/security layer that sets:

- HSTS;
- modern TLS policy;
- proxy/client IP propagation rules;
- request size limits;
- timeout and connection limits.

The FastAPI app must not trust arbitrary forwarded IP headers unless the trusted proxy contract is configured.

## Secret Management

Rules:

- `.env.example` contains names and local placeholders only.
- `.env` is ignored and never committed.
- Production secrets are injected by the platform secret manager or deployment runtime.
- Secrets are rotated through documented operations.
- Application configuration never logs the full secret.
- Different environments use different JWT secrets, database credentials, and Redis credentials.

## Sensitive Data Handling

Initial sensitive fields include passwords, tokens, passwords resets, government identifiers if ever introduced, salary data in future HR modules, and customer credentials in future integrations.

Requirements:

- minimize collection;
- mask logs and audit snapshots;
- restrict API fields by audience;
- avoid exporting sensitive fields without a dedicated permission and audit event;
- define retention periods before storing new sensitive categories.

## Audit Logging

Sensitive operations include:

- create/update/disable user;
- reset password;
- move/disable department;
- create/update role;
- assign/revoke role or permission;
- create/update workspace/menu;
- publish/withdraw announcement;
- export audit/personal/business-sensitive data;
- security configuration changes.

Audit records include actor, module, action, target, request metadata, result, duration, and safe before/after snapshots where justified. Audit writes must be durable and protected from ordinary CRUD; failure handling must not silently lose security evidence.

## Account Lifecycle

| State | Security result |
| --- | --- |
| Active | Normal authentication/authorization |
| Disabled | No login/API access; roles retained |
| Locked | Temporary no login until unlock/expiry |
| Resigned | Historical data retained; no login/API access |
| Soft deleted | Excluded from normal operations; audit/history retained |

Disabling or recording resignation should revoke active refresh tokens. Existing short-lived access tokens must still encounter active-account checks for protected operations.

## Security Roadmap

Phase 1A (complete):

- employee identity and organization persistence only;
- no authentication routes, JWT/password code, or credential storage.

Phase 1B (complete):

- password hashing (Argon2id) and password policy;
- login/refresh/logout/current-user endpoints;
- refresh rotation, lineage, and reuse detection with session revocation;
- account-state checks (disabled/locked/resigned/soft-deleted denied, on-leave allowed);
- login evidence logging;
- Redis-backed login throttling;
- no RBAC dependencies yet; those follow in Phase 2.

Phase 2A (complete):

- role/permission/user-role/role-permission persistence (migration `0003_rbac_foundation`);
- code-owned permission catalog with explicit, dry-run-able sync;
- effective-permission resolution service (union semantics, no cache);
- system role seed and CLI role assignment;
- `/auth/me` carries roles and permission codes as display data;
- no enforcement dependencies yet — those are Phase 2B.

Phase 2B (complete):

- `require_permission(...)` dependency with `AuthorizationContext` (request-scoped, Depends-cached);
- 401/403 separation preserved and regression-tested (15-case matrix);
- fail-fast catalog validation for permission codes.

Phase 2C (complete):

- all 34 management endpoints gated by `require_permission(...)` with catalog constants; operator identity (`assigned_by`) is server-derived, never client-submitted;
- user creation cannot mint credentials (no password fields accepted or stored);
- self-lockout protection: the operator cannot disable/resign themselves, directly or via PATCH (`409`);
- role-permission replacement validates every code against the catalog (unknown/disabled `422`); `super_admin` rejects stored authorization (`409`);
- sensitive operations (user lifecycle, department move, role/permission assignment) carry documented audit intent for the Phase 5 audit system;
- immediate-effect guarantees regression-tested: disable/resign and every grant/remove/replacement change authorization on the next request.

Phase 3:

- workspace/menu authorization;
- navigation cache invalidation.

Phase 4:

- announcement audience authorization and content sanitization.

Phase 5:

- audit export controls;
- security regression suite;
- production secret/rotation runbook.
