# API Design

## API Principles

- API first: web, mobile, automation, integrations, and future AI clients use the same versioned contracts.
- One versioned namespace: `/api/v1`.
- Resources use plural kebab-case paths where a hyphen improves readability.
- HTTP methods express operation intent.
- Responses are predictable and typed.
- Authentication, action permission, workspace access, and data scope are backend concerns.

## URL Conventions

```text
/api/v1/health
/api/v1/health/ready
/api/v1/auth/login
/api/v1/auth/refresh
/api/v1/auth/logout
/api/v1/auth/me
/api/v1/users
/api/v1/users/{user_id}
/api/v1/departments
/api/v1/departments/{department_id}
/api/v1/departments/tree
/api/v1/positions
/api/v1/roles
/api/v1/permissions
/api/v1/workspaces
/api/v1/workspaces/{workspace_id}/menus
/api/v1/announcements
/api/v1/audit-logs
```

Rules:

- Paths identify resources, not internal function names.
- Sub-resources represent clear ownership (`/roles/{role_id}/permissions`).
- Avoid verbs except unavoidable actions such as `login`, `refresh`, `logout`, `publish`, and `withdraw`.
- Prefer a small action endpoint over an overloaded `PATCH` when the state transition has security/audit meaning.

## HTTP Methods

| Method | Use |
| --- | --- |
| `GET` | Read one resource, list resources, or read a derived view |
| `POST` | Create a resource or execute a non-idempotent action |
| `PUT` | Replace a representation when semantically appropriate |
| `PATCH` | Partial update with explicit optional fields |
| `DELETE` | Physical delete only where allowed; core platform records usually use disable/archive |

Creation normally returns `201`. Most reads return `200`. Acceptance of an async job may return `202` only when job tracking is actually implemented.

## Response Envelope

Successful responses use:

```json
{
  "success": true,
  "data": {},
  "meta": null
}
```

`meta` is omitted or `null` for simple responses. It contains pagination, totals, or generated execution metadata.

Error responses use:

```json
{
  "success": false,
  "error": {
    "code": "AUTHORIZATION_FAILED",
    "message": "You do not have permission to perform this action.",
    "details": {}
  }
}
```

The code is a stable machine-readable identifier. The message is safe for the client. Details may contain field validation or non-sensitive context.

## Pagination

List endpoints use offset pagination for administrative screens initially:

```text
GET /api/v1/users?page=1&page_size=20
```

Constraints:

- `page` starts at 1.
- `page_size` has a bounded maximum, for example 100.
- Default sorting is explicit and stable, usually `created_at DESC, id DESC`.
- The response metadata includes at least `page`, `page_size`, `total`, and `total_pages`.

Example:

```json
{
  "success": true,
  "data": [
    {}
  ],
  "meta": {
    "page": 1,
    "page_size": 20,
    "total": 143,
    "total_pages": 8
  }
}
``+

Cursor pagination may be introduced for high-volume activity, audit, or integration streams. It should expose an opaque cursor and preserve a deterministic tie-breaker.

## Filtering And Sorting

Filters are explicit query parameters:

```text
GET /api/v1/users?status=active&department_id=...&keyword=li
```

Rules:

- Unknown filter parameters are rejected or explicitly ignored by a shared convention, not silently interpreted.
- Sorting uses a allowlisted field map, for example `sort=created_at:desc`.
- Free-text search has module-specific columns and indexes.
- IDs are UUIDs and rejected early if malformed.

## API Modules

### Auth (implemented in Phase 1B)

Endpoints:

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

Login response contract:

```json
{
  "success": true,
  "data": {
    "access_token": "<jwt>",
    "token_type": "bearer",
    "expires_in": 1800
  },
  "meta": null
}
```

The login and refresh response bodies expose only the access token. The backend sets the refresh token as an `HttpOnly`, `Secure` (in production), `SameSite=Lax` cookie scoped to `Path=/api/v1/auth` and never returns it in JSON. Frontend JavaScript must not read or store the refresh token.

- `POST /auth/login`: validates credentials (generic `401 AUTHENTICATION_FAILED` for any failure; `429 RATE_LIMITED` when the Redis brute-force threshold is exceeded) and establishes the refresh-cookie session.
- `POST /auth/refresh`: authenticates from the cookie, rotates it inside one transaction, and returns a new access token. Reuse of a rotated token returns `401` and revokes the whole session family. Requires a browser `Origin` header to match `TMT_CORS_ORIGINS` (absent `Origin` allowed for non-browser clients).
- `POST /auth/logout`: revokes the refresh-token family, marks the session revoked in Redis, clears the cookie, and always answers `200` (idempotent, even without a cookie). Same `Origin` validation as refresh.
- `GET /auth/me`: resolves the current account from the access token plus active server-side account/session state (`401 SESSION_REVOKED` for revoked sessions).

`/auth/me` returns the identity profile plus, since Phase 2A, `roles` (stable role codes) and `permissions` (effective permission codes, sorted):

```json
{
  "success": true,
  "data": {
    "id": "...",
    "username": "operator",
    "name": "...",
    "employment_status": "active",
    "account_status": "active",
    "roles": ["system_admin"],
    "permissions": ["system:user:list", "system:user:view"],
    "primary_department": {"id": "...", "name": "Engineering"},
    "primary_position": null,
    "last_login_at": "..."
  },
  "meta": null
}
```

These fields are display data; visible UI never replaces backend permission checks. Workspace access and menu data remain future contracts and are intentionally absent.

### Protected endpoints (Phase 2B)

Every protected endpoint declares its permission through the reusable
dependency, and business code references catalog constants rather than string
literals:

```python
from app.modules.rbac.catalog import Permissions
from app.modules.rbac.dependencies import require_permission

@router.get(
    "/users",
    dependencies=[Depends(require_permission(Permissions.USER_LIST))],
)
async def list_users(...) -> SuccessEnvelope[...]: ...
```

Status semantics stay strict: `401` (`AUTHENTICATION_FAILED`) for missing,
invalid, expired tokens, revoked sessions, or inactive accounts; `403`
(`AUTHORIZATION_FAILED`, `details` empty) for an authenticated identity
without the required permission. The 403 body never echoes the required
permission code or any authorization structure.

Recommended initial split:

```text
GET /api/v1/auth/me
GET /api/v1/auth/workspaces
GET /api/v1/auth/menus?workspace_id=...
```

The combined endpoint is convenient for initial page load, but workspace menus can be large and workspace-specific. Dedicated endpoints reduce accidental overfetch and make cache invalidation clearer. If a combined bootstrap endpoint is added later, it must remain read-only and not become an authorization decision. Page reloads may call refresh followed by these read endpoints to restore a session.

### Users (implemented in Phase 2C)

```text
GET    /api/v1/users                              system:user:list
GET    /api/v1/users/{user_id}                    system:user:view
POST   /api/v1/users                              system:user:create      -> 201
PATCH  /api/v1/users/{user_id}                    system:user:update
POST   /api/v1/users/{user_id}/disable            system:user:disable
POST   /api/v1/users/{user_id}/enable             system:user:disable
POST   /api/v1/users/{user_id}/resign             system:user:update
GET    /api/v1/users/{user_id}/roles              system:role:view
POST   /api/v1/users/{user_id}/roles/{role_id}    system:role:assign
DELETE /api/v1/users/{user_id}/roles/{role_id}    system:role:assign
```

Contracts:

- list: `page`/`page_size`/`keyword` (username/name/email/employee_no ilike)/`account_status`/`employment_status`/`department_id`/`order_by` (allowlist `created_at|username|employee_no`)/`order` (`asc|desc`); `department_id` is a query condition, not a data-scope enforcement.
- detail: identity fields plus `primary_department`/`primary_position` summaries; credentials are never exposed.
- create: employee identity only — the request schema has no password field; stray `password`/`password_hash` values are ignored and no credential row is created.
- lifecycle: disable/enable use the `system:user:disable` code; resign reuses `system:user:update` (employment state, separate from account state). The operator cannot disable/resign themselves — directly or through PATCH (`409`).
- `POST /users/{user_id}/roles/{role_id}` is idempotent (`newly_assigned` flag); `assigned_by` is always the authenticated operator. Disabled roles are rejected with `409`.

Users are not physically deleted.

### Departments (implemented in Phase 2C)

```text
GET   /api/v1/departments                            system:department:list
GET   /api/v1/departments/tree                       system:department:list
GET   /api/v1/departments/{department_id}            system:department:view
POST  /api/v1/departments                            system:department:create -> 201
PATCH /api/v1/departments/{department_id}            system:department:update
POST  /api/v1/departments/{department_id}/move       system:department:move
POST  /api/v1/departments/{department_id}/disable    system:department:disable
POST  /api/v1/departments/{department_id}/enable     system:department:disable
```

Move reuses Phase 1A cycle prevention: `parent_id == self` and moves into a descendant return `422`. The tree endpoint returns composed nodes from a recursive CTE and contains only active departments. Audit intent for moves is documented in the service for the future audit system.

### Positions (implemented in Phase 2C)

```text
GET   /api/v1/positions                          system:position:list
GET   /api/v1/positions/{position_id}            system:position:view
POST  /api/v1/positions                          system:position:create -> 201
PATCH /api/v1/positions/{position_id}            system:position:update
POST  /api/v1/positions/{position_id}/disable    system:position:disable
POST  /api/v1/positions/{position_id}/enable     system:position:disable
```

Positions describe organizational jobs and never produce role or permission side effects.

### Roles (implemented in Phase 2C)

```text
GET   /api/v1/roles                              system:role:list
GET   /api/v1/roles/{role_id}                    system:role:view
POST  /api/v1/roles                              system:role:create -> 201
PATCH /api/v1/roles/{role_id}                    system:role:update
POST  /api/v1/roles/{role_id}/disable            system:role:disable
POST  /api/v1/roles/{role_id}/enable             system:role:disable
GET   /api/v1/roles/{role_id}/permissions        system:role:view
PUT   /api/v1/roles/{role_id}/permissions        system:role:assign
```

`code` and `is_system` cannot be changed through the API (the update schema does not declare them and the service ignores them). System roles reject disable. `PUT .../permissions` replaces the whole explicit permission set in one transaction and reports `added`/`removed`/`unchanged`; unknown or disabled codes return `422`; `super_admin` returns `409` because its powers are dynamic expansion, never stored grants.

### Permissions (implemented in Phase 2C, read-only)

```text
GET /api/v1/permissions                          system:permission:list
GET /api/v1/permissions/{permission_id}          system:permission:list
```

Filters: `module`, `kind`, `status`, `keyword`. The catalog is code-owned; permission definitions change only through `sync-permissions`, so no mutation endpoints exist (unregistered methods answer `405`).

### Workspaces And Menus

Not implemented yet — Phase 3A delivered the persistence foundation only: the code-owned workspace registry (`sync-workspaces` CLI), `workspaces`/`workspace_departments`/`menus` tables, and workspace access permission codes (`workspace:<code>:access`, derived from the registry into the permission catalog). No workspace or menu endpoint exists; even workspace rows are created by the registry sync, not by API.

Planned (Phase 3B+):

```text
GET   /api/v1/auth/workspaces
GET   /api/v1/auth/menus?workspace_id=...
GET   /api/v1/workspaces/{workspace_id}/menus
```

Management endpoints for workspaces/menus are deliberately deferred until a product need exists; the registry stays the definition of record. Workspace access enforcement (`require_workspace_access`) arrives with Phase 3B and uses the same `require_permission` machinery — menu visibility remains UX only.

### Announcements

Planned:

```text
GET   /api/v1/announcements
POST  /api/v1/announcements
GET   /api/v1/announcements/{announcement_id}
PATCH /api/v1/announcements/{announcement_id}
POST  /api/v1/announcements/{announcement_id}/publish
POST  /api/v1/announcements/{announcement_id}/withdraw
```

The recipient list reflects scope at publication time for historical announcements.

### Portal

Initial planned endpoints:

```text
GET /api/v1/portal/welcome
GET /api/v1/portal/my-workspaces
GET /api/v1/portal/announcements
GET /api/v1/portal/quick-links
```

Phase 4 defines the exact shape. Portal APIs compose public module services; they must not duplicate each module's permission logic.

### Audit Logs

Planned:

```text
GET /api/v1/audit-logs
GET /api/v1/audit-logs/{audit_log_id}
```

No update/delete API is exposed.

## Error Contract

Canonical codes and status codes:

| Code | HTTP | Meaning |
| --- | --- | --- |
| `AUTHENTICATION_FAILED` | 401 | Missing, expired, invalid, or revoked credentials |
| `AUTHORIZATION_FAILED` | 403 | Authenticated but not allowed |
| `RESOURCE_NOT_FOUND` | 404 | Resource absent or intentionally hidden by scope |
| `RESOURCE_CONFLICT` | 409 | Unique/duplicate or incompatible current state |
| `REQUEST_VALIDATION_FAILED` | 422 | Schema/business validation failure |
| `RATE_LIMITED` | 429 | Too many requests or too many authentication attempts |
| `INTERNAL_ERROR` | 500 | Unexpected server failure |

A 401 response should include `WWW-Authenticate` when credentials are missing or invalid. Future modules may add specific codes, but must not invent a new envelope.

## Validation Style

- Request models reject unknown important fields according to the chosen Pydantic configuration.
- Optional does not mean unvalidated.
- IDs, enums, email/phone formats, pagination bounds, and timezone-bearing datetimes are validated at the boundary.
- Business uniqueness and state-transition validation happen in services and translate to `ConflictError`/`ValidationError`.

## OpenAPI

FastAPI OpenAPI is served at `/api/openapi.json`. Every route declares schemas, response models, tags, summaries, and error responses where relevant. Generated docs are part of the contract; hand-written API documentation must stay synchronized with it.

## Compatibility Rules

Within `/api/v1`:

- Remove fields or change types only through a documented migration plan.
- Add optional response fields conservatively.
- Do not repurpose a status code or permission code.
- Preserve stable error codes.
- Deprecate before removing and document the replacement.

New major contracts go under a new version prefix rather than breaking `/api/v1` for all internal clients.
