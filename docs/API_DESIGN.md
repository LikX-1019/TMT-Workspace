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

## Planned API Modules

### Auth

Planned:

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

`/auth/me` returns the current user profile, active roles, effective permission codes, workspace access, and menu/navigation data or references to dedicated endpoints.

Recommended initial split:

```text
GET /api/v1/auth/me
GET /api/v1/auth/workspaces
GET /api/v1/auth/menus?workspace_id=...
```

The combined endpoint is convenient for initial page load, but workspace menus can be large and workspace-specific. Dedicated endpoints reduce accidental overfetch and make cache invalidation clearer. If a combined bootstrap endpoint is added later, it must remain read-only and not become an authorization decision.

### Users

Planned:

```text
GET    /api/v1/users
POST   /api/v1/users
GET    /api/v1/users/{user_id}
PATCH  /api/v1/users/{user_id}
POST   /api/v1/users/{user_id}/disable
POST   /api/v1/users/{user_id}/enable
POST   /api/v1/users/{user_id}/roles
DELETE /api/v1/users/{user_id}/roles/{role_id}
```

Users are not physically deleted.

### Departments

Planned:

```text
GET   /api/v1/departments/tree
GET   /api/v1/departments
POST  /api/v1/departments
GET   /api/v1/departments/{department_id}
PATCH /api/v1/departments/{department_id}
POST  /api/v1/departments/{department_id}/move
POST  /api/v1/departments/{department_id}/disable
```

Department moves require special validation and audit.

### Positions, Roles, Permissions

Each has list/create/read/update contracts. Sensitive operations are explicit:

```text
PUT    /api/v1/roles/{role_id}/permissions
POST   /api/v1/users/{user_id}/roles
DELETE /api/v1/users/{user_id}/roles/{role_id}
```

### Workspaces And Menus

Planned:

```text
GET   /api/v1/workspaces
POST  /api/v1/workspaces
PATCH /api/v1/workspaces/{workspace_id}
GET   /api/v1/workspaces/{workspace_id}/menus
POST  /api/v1/workspaces/{workspace_id}/menus
PATCH /api/v1/menus/{menu_id}
POST  /api/v1/menus/{menu_id}/move
```

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

