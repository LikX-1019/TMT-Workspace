# Security Design

## Security Principles

1. Identity, action permission, workspace access, and data scope are all verified on the backend.
2. Fail closed when required context is missing or invalid.
3. Never expose secrets, tokens, stack traces, internal SQL, or unrestricted enumeration errors.
4. Prefer maintained security libraries over custom cryptographic code.
5. Record evidence for sensitive administrative actions.

## Authentication

Phase 1 uses local employee accounts with username/password authentication and JWT access tokens. The architecture reserves an authentication-provider boundary for future enterprise WeChat, Feishu, LDAP, or OIDC integration, but no provider becomes a core dependency.

Login requirements:

- constant-time password verification through a maintained library;
- generic failure message that does not reveal whether username or password was wrong;
- login attempt logging;
- brute-force throttling by username, account, IP, and optionally device;
- locked/disabled/resigned account rejection;
- successful login updates `last_login_at` and writes `login_logs`.

## Password Policy

Initial policy:

- minimum 12 characters;
- reject exact username/email/employee number;
- require breadth across character classes without forcing awkward rotation by default;
- support future breach-password checking;
- hash with Argon2 or bcrypt through a maintained library.

Phase 1 must define reset flows, administrator-forced reset, and reuse restrictions. Passwords are never recoverable or logged.

## Token Architecture

Access tokens:

- short-lived, initially 30 minutes or less;
- stateless claims include user ID, token type, issued time, expiry, and minimal session reference;
- never contain passwords, refresh tokens, broad permission snapshots that can become stale, or secrets.

Refresh tokens:

- longer-lived but revocable;
- delivered to the browser only as `HttpOnly`, `Secure`, `SameSite` cookies;
- never readable by frontend JavaScript and never returned in the login response body;
- stored server-side as a secure hash only;
- rotated on use;
- support replacement lineage (`replaced_by_id`) and reuse detection;
- revoked at logout, password reset, administrator disable, role/security incident, or account resignation.

The platform must check account/session state before trusting an unexpired access token for sensitive operations. Stateless JWT alone is not a revocation mechanism.

Recommended browser flow:

1. client authenticates;
2. server returns only the access token in the response body and sets the refresh cookie;
3. client sends `Authorization: Bearer <access-token>`;
4. dependencies validate signature, expiry, token type, and active account/session state;
5. refresh endpoint authenticates from the cookie, rotates it, and issues a new access token;
6. reuse or logout revokes the token family.

Cookie requirements:

- `HttpOnly`;
- `Secure` in development over HTTPS and always in production;
- `SameSite=Lax` or `Strict` after an explicit cross-site product/security decision;
- scoped path (normally the refresh endpoint path where operationally practical);
- CSRF protection for cookie-authenticated state-changing endpoints, using origin checks plus a maintained CSRF mechanism where needed;
- explicit cookie name, lifetime, domain, and rotation policy before Phase 1B.

Access-token persistence is not approved. A page reload restores authentication through the valid refresh-cookie endpoint, not by reading a token from browser storage.

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

Redis is reserved for shared counters because API replicas need consistent limits.

Initial controls:

- global/IP request throttling where appropriate;
- strict login throttling by IP and target account;
- exponential backoff or temporary lock after repeated failures;
- enhanced logging/security alerting when thresholds are exceeded.

Limits must be configurable per environment and must not leak account existence through dramatically different responses.

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

Phase 1:

- password hashing;
- login/refresh/logout;
- account-state checks;
- login logging;
- basic throttling;
- initial RBAC dependencies.

Phase 2:

- full permission checks and permission tests;
- role/permission audit;
- token/session revocation hardening.

Phase 3:

- workspace/menu authorization;
- navigation cache invalidation.

Phase 4:

- announcement audience authorization and content sanitization.

Phase 5:

- audit export controls;
- security regression suite;
- production secret/rotation runbook.
