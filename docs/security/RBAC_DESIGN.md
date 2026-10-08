# RBAC Design

## Objective

The platform uses role-based access control to separate three questions:

1. Who is the authenticated employee? (Phase 1B authentication)
2. Which roles does that employee hold? (Phase 2A persistence + resolution)
3. What capabilities and data ranges do those roles enable? (Phase 2B enforcement; scope later)

Frontend menu rendering is a UX convenience. Every protected operation is enforced by backend dependencies and service/repository boundaries.

## Implementation Status

Phase 2A delivers the persistence and resolution foundation: `roles`,
`permissions`, `user_roles`, `role_permissions` tables, the code-owned
permission catalog (`app/modules/rbac/catalog.py`), the
`PermissionCatalogService.sync` CLI operation, and the
`AuthorizationService` that resolves role codes and effective permission
codes. `/auth/me` carries `roles` and `permissions` as display data.

Phase 2B delivers enforcement: `app/modules/rbac/dependencies.py` exposes
`require_permission(...)` and the request-scoped `AuthorizationContext`.

Phase 2C delivers the management surfaces on top of that enforcement:

- User/Department/Position/Role management APIs and both assignment APIs,
  each endpoint declaring its catalog permission code through
  `require_permission(...)` (34 protected endpoints; `auth/login` remains
  intentionally anonymous);
- role-permission configuration uses whole-set replacement
  (`PUT /roles/{id}/permissions`), computed and written in one transaction;
  unknown or disabled codes are rejected (`422`), and `super_admin` rejects
  explicit authorization (`409`) because its powers are dynamic expansion;
- user-role grants are idempotent, record the authenticated operator as
  `assigned_by`, and refuse disabled roles (`409`);
- no permission cache exists: every management mutation is visible to
  authorization on the next request;
- Phase 2C still does **not** deliver row-level data-scope enforcement
  (`department` filters on list endpoints are query conditions, not scopes)
  and workspace authorization (Phase 3).
- Phase 3A makes the reserved `workspace` kind real: the code-owned workspace
  registry (`app/modules/workspaces/registry.py`) deterministically derives one
  `workspace:<code>:access` permission per registered workspace into the
  catalog, so `sync-permissions` writes them like any other code. No system
  role receives workspace access automatically — it is business authorization
  configured through `RolePermission`. Nothing enforces it yet; the database
  stores workspaces, `workspace_departments` (metadata, never grants), and
  `menus` (navigation metadata whose `permission_code` is UX visibility only).

Authentication (who are you?) and authorization (what can you do?) remain
separate: `get_current_user` answers identity only, and no permission check
is embedded in authentication.

## Core Relationships

```text
User
 --> UserRole --> Role
                   --> RolePermission --> Permission
                   --> data_scope_type (stored policy; unenforced)
```

Effective action permissions are the union of all active role permissions for the user. If any role grants a required permission, the action-permission check passes; data scope is then applied independently.

## Permission Kinds

| Kind | Purpose | Example |
| --- | --- | --- |
| `workspace` | Controls awareness/access to a first-class workspace | `workspace:operation:access` |
| `menu` | Represents a menu/page capability when it is not already covered by an action | `system:user:page` |
| `action` | Controls a backend operation | `system:user:create` |
| `data_scope` | Reserved for explicitly configurable scope capabilities | `system:user:scope:department` |

`data_scope` is usually modeled as role policy rather than a large number of separate permission codes. The permission kind exists so a future delegated or custom scope capability has a stable place in the model.

## Permission Code Grammar

```text
<workspace-or-system>:<resource>:<action>[:<qualifier>]
```

Rules:

- Use lowercase ASCII.
- Separate logical parts with `:`.
- Use singular or natural resource nouns consistently (`user`, `role`, `menu`).
- Use stable verbs: `access`, `view`, `list`, `create`, `update`, `delete`, `disable`, `enable`, `assign`, `revoke`, `publish`, `withdraw`, `export`, `import`.
- Do not encode employee IDs, department IDs, workspace row IDs, or volatile names in a permission code.
- Do not reuse a code for a different backend operation.

### System examples

```text
system:user:list
system:user:view
system:user:create
system:user:update
system:user:disable
system:user:assign-role

system:department:list
system:department:create
system:department:update
system:department:move

system:position:list
system:position:create
system:position:update

system:role:list
system:role:create
system:role:update
system:role:assign

system:permission:list
system:permission:assign

system:workspace:list
system:workspace:create
system:workspace:update

system:menu:list
system:menu:create
system:menu:update

system:announcement:list
system:announcement:create
system:announcement:publish
system:announcement:withdraw

system:audit-log:list
system:audit-log:export
```

### Business workspace examples

Workspace access codes are **not hand-maintained here**: the registry
generates `workspace:<code>:access` for every registered workspace (currently
`operation`, `product`, `procurement`, `warehouse`, `customer-service`,
`finance`, `hr`, `tech`). The `operation:*`/`procurement:*`/`warehouse:*`
action codes below are future business capability examples, not catalog
entries yet.

```text
workspace:operation:access
operation:product:list
operation:product:create
operation:product:update
operation:product:export

workspace:procurement:access
procurement:order:list
procurement:order:create
procurement:order:approve

workspace:warehouse:access
warehouse:inventory:view
warehouse:inventory:adjust
```

## Role Design

Seeded system roles (created by `python -m app.cli sync-permissions`, `is_system=true`):

| Role code | Assignment policy | Purpose |
| --- | --- | --- |
| `super_admin` | dynamic: resolves to every active permission at authorization time | Break-glass platform administration |
| `system_admin` | explicit: all current catalog permissions, never future ones automatically | Normal platform administration |
| `security_auditor` | explicit: `list`/`view` codes only | Read-only security review |

Business workspaces define their own roles later, for example `operation_operator` or `procurement_operator`. Roles should express responsibility, not individual people or departments.

Role rules:

- Role code is the stable identifier and is never updated after creation; display names and descriptions may change.
- System roles cannot be disabled or soft-deleted through `RoleService`; retiring one is an explicit operator/data action.
- Roles soft-delete (`deleted_at`); historical `user_roles` rows keep resolving to the row, but deleted/disabled roles contribute no permissions.
- `roles.data_scope_type` is stored configuration only in Phase 2A. `custom` scope will require a `role_data_scope_departments` table (deferred to Phase 3.5) — it is not created yet.
- Role modifications will require audit records once the audit system exists.

## Permission Catalog Ownership

Permission definitions are a **development contract** in
`app/modules/rbac/catalog.py` (`SYSTEM_PERMISSIONS`). The database mirrors
the catalog; it is not a place to invent codes. Role-permission assignment
is operational configuration. This keeps every code mapped to a real (or
planned) backend enforcement point — a UI-created code would have nothing
checking it.

Phase 2A catalog: 23 `action` codes for the `system` namespace (`system:user:*`, `system:department:*`, `system:position:*`, `system:role:*`, `system:permission:list`). `workspace`/`menu` kinds remain reserved model values with no catalog data; no `data_scope` permission codes exist because data scope is role policy, not per-row permission data.

## Assignment Rules

Phase 2:

- Users receive roles only through `user_roles` (`AuthorizationService.assign_role`, idempotent; `assigned_by` records the acting administrator).
- No direct user-to-permission table is implemented.
- One user may receive multiple roles; grants are unique per `(user_id, role_id)`.
- Only active, non-deleted roles can be granted.

Later extension:

- Temporary role assignment windows;
- delegated administration;
- emergency elevation with expiry and enhanced audit.

These are additive to `user_roles`; they must not permit a hidden bypass of role resolution.

## Authorization Flow

Steps 1–5 below are implemented (steps 1–3 by Phase 2A `AuthorizationService`,
steps 4–5 by Phase 2B `require_permission`); the rest arrive in later phases:

1. Resolve authenticated user from access-token validation and active session state. `get_current_user` answers this alone — authentication never grows permission queries.
2. Reject disabled, locked, resigned, or soft-deleted users (401 at the authentication layer).
3. Load active roles and effective permission codes (union, deduplicated) into the request-scoped `AuthorizationContext` — resolved once per request through FastAPI `Depends` caching, never a cross-request cache.
4. Check action permission via `require_permission(...)`: membership in the context's effective set, answered by `AuthorizationService`. Denied → `AuthorizationError` → HTTP 403 `AUTHORIZATION_FAILED` (response body never echoes the required permission).
5. Check workspace permission if the route belongs to a workspace. *(Phase 3)*
6. Resolve role data-scope policy and construct an explicit data context. *(later phase)*
7. Apply scope at query or mutation time. *(later phase)*
8. Audit the operation when it is sensitive. *(audit system phase)*

Permission codes passed to `require_permission` must come from the
`Permissions` constants in the catalog; the dependency validates the code
against `CATALOG_PERMISSION_CODES` at construction time and raises `ValueError`
for unknown codes — a typo is a programming error that fails at import/startup,
never a silent wall of 403s.

A request that fails action permission returns `403`; a request that is authenticated but lacks a valid token returns `401`. A resource outside the allowed scope should normally return `404` to avoid confirming existence, unless product/security explicitly requires `403`.

### Effective Permission Resolution

```text
effective(user) =
  union of p in permissions where
    exists user_role(user, r)        with r.status = active and r.deleted_at is null
    and role_permission(r, p)        (grant row exists)
    and p.status = active
```

- Union-only: no deny permissions, no precedence, no user-direct overrides (Phase 2A contract, see `SECURITY.md`).
- Set semantics deduplicate codes shared across roles; resolution is a single joined query (no N+1).
- `super_admin` expansion: if any active role of the user is the `is_system` role with code `super_admin`, the result is the set of all active permission codes. See `SECURITY.md` for why this is resolved dynamically instead of stored as rows.

No permission cache exists in Phase 2A: resolution queries PostgreSQL per request until profiling justifies a cache plus its invalidation contract.

## Dynamic Menu Contract

The authenticated navigation API will derive menus from:

1. workspaces the user may access;
2. active menus in those workspaces;
3. menu type and parent/child relationships;
4. permission codes the user actually holds;
5. visible/status/sort metadata.

Menus may be cached, but cache invalidation must occur when menus, roles, permissions, or user-role assignments change. The API must still verify permissions per request; it must not rely on cache age as an authorization boundary.

## Initial Bootstrap

The bootstrap path is explicit, CLI-driven, and never bakes business users into migrations:

```bash
uv run --directory backend python -m app.cli create-local-credential --username <operator>   # Phase 1B password
uv run --directory backend python -m app.cli sync-permissions          # catalog + system roles + grants
uv run --directory backend python -m app.cli assign-role --username <operator> --role super_admin
```

`sync-permissions` supports `--dry-run` and reports `create` / `update` / `re-enable` / `stale` / unchanged / role / grant lines. The initial password is never committed. No default `admin`/`admin` account exists; nothing in code matches on usernames.

## Anti-Patterns

Do not introduce:

- permission checks only in frontend routing;
- `if user.is_admin` scattered through service methods as the sole authorization mechanism;
- position-based authorization;
- direct user-permission rows;
- role names such as `temp_li_2026_user_editor`;
- per-request SQL policies without a documented scope context;
- unbounded `*` permissions;
- permission code changes without migration/compatibility review.
