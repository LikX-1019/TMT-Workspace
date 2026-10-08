# Domain Model

Phase 1A implements the organization and identity persistence foundation; Phase 1B adds the authentication aggregates (`LocalCredential`, `RefreshToken`, `LoginLog`). RBAC, workspaces, and audit remain future contracts and must not be inferred from these tables.

## Model Principles

- Organization and authorization are deliberately separated.
- A department can exist without a workspace; a workspace can serve many departments.
- Employees and administrative history are retained; core organization/identity records are not physically deleted.
- A role is a permission bundle; a position is an organizational job.
- Every sensitive model has stable identity, UTC timestamps, and explicit lifecycle state.

## Entity Overview

Implemented in Phase 1A:

```text
User --- UserDepartment --- Department
  |                         |
  |                         +--- Department (parent_id)
  +--- UserPosition --- Position
```

Implemented in Phase 2A:

```text
User --- UserRole --- Role --- RolePermission --- Permission
                          |
                          +--- data_scope_type (stored policy; unenforced)
```

Planned and explicitly deferred:

```text
Role --- role_data_scope_departments (Phase 3.5, custom scope only)

Workspace --- WorkspaceDepartment --- Department
Workspace --- Menu --- Permission

Announcement --- AnnouncementScope ---> Department / Role / User

AuditLog / LoginLog / RefreshToken ---> User
```

## User

`User` represents an employee or system operator identity. It is not an authentication credential aggregate.

Implemented fields:

| Field | Meaning |
| --- | --- |
| `id` | Stable UUID |
| `employee_no` | Company employee number |
| `username` | Unique login identifier |
| `name` | Display/legal name for internal UI |
| `email` | Unique where present |
| `mobile` | Unique where present |
| `avatar_url` | Optional internal asset reference |
| `employment_status` | `active`, `resigned`, `on_leave`, or equivalent |
| `account_status` | `active`, `disabled`, `locked`, or equivalent |
| `primary_supervisor_id` | Direct manager for approval/data scope workflows |
| `last_login_at` | Last successful authentication |
| `deleted_at` | Nullable soft-delete marker |
| audit fields | Creation/update metadata |

Rules:

- `employee_no` and `username` are unique for the full record lifecycle, including soft deletion.
- `email` and `mobile` are nullable and unique where present.
- Password hashing and login credentials live in the separate `LocalCredential` aggregate (Phase 1B), never on `users`.
- A resigned employee remains queryable for historical and audit purposes.
- `account_status=disabled` blocks login and API access even if roles remain assigned.
- Role assignment is through `user_roles`; direct user-permission grants are not part of the initial platform.
- Organization membership is not stored only as free text on the user row.

## LocalCredential

Implemented in Phase 1B (migration `0002`). At most one credential row per user (`user_id` unique), kept off `users` so identity survives credential changes and future SSO providers.

Fields:

- `id`
- `user_id` (unique)
- `password_hash` (Argon2id via pwdlib)
- `password_changed_at`
- `must_change_password`
- audit fields

Verification upgrades hashes whose Argon2 parameters fall behind the current policy on next successful login.

## Department

`Department` forms a company organization tree.

Planned fields:

- `id`
- `parent_id`
- `name`
- `code`
- `leader_id`
- `sort`
- `status`
- `deleted_at`
- timestamp/audit fields

Rules:

- Unlimited hierarchy is supported through the adjacency model.
- A department must not become its own ancestor.
- `code` is unique for the full record lifecycle, including soft deletion.
- Re-parenting must be audited because it can change department-based data scope.
- The first implementation uses `departments.parent_id` plus PostgreSQL recursive CTEs for tree reads and descendant lookup. A materialized closure table is a future optimization only if measured query frequency, organization size, or database plan evidence requires it.

## UserDepartment

This association supports multiple department membership without temporal history.

Implemented fields:

- `user_id`
- `department_id`
- `is_primary`
- `created_at` / `updated_at`

One user has at most one primary assignment. Additional assignments may represent matrix organizations or temporary roles. The active primary department is the default basis for future department data scope.

## Position

`Position` describes a job title or organizational role, such as Operations Supervisor or Developer.

Implemented fields:

- `id`
- `name`
- `code`
- `description`
- `sort`
- `status`
- timestamp/audit fields

Rules:

- A position has no direct permission meaning.
- A user may have one or more position assignments.
- Reporting and organizational views use positions; authorization checks use roles.

## UserPosition

Implemented fields:

- `user_id`
- `position_id`
- `is_primary`
- `created_at` / `updated_at`

This keeps organizational title separate from system access. For example, two Finance Managers can receive different roles, and one Developer can temporarily hold a Product Manager position without changing permissions.

## Role

Implemented in Phase 2A. `Role` is a named authorization bundle, for example `super_admin`, `system_admin`, or `security_auditor`.

Fields:

- `id`
- `name` (display; mutable)
- `code` (stable identifier; immutable after creation, unique across the lifecycle including soft deletion)
- `description`
- `data_scope_type` (`all` / `department` / `department_and_children` / `self` / `custom`; stored policy only — no query enforcement exists yet)
- `sort`
- `status` (`active` / `disabled`)
- `is_system`
- `deleted_at`
- timestamp fields

Rules:

- System roles cannot be disabled or deleted through ordinary management; retiring one is an explicit operator/data action.
- Role code is stable; display names are not used as identifiers.
- A role may carry a data-scope policy, but data scope does not replace action permission and is not enforced in Phase 2A.
- Since Phase 2C, role lifecycle and role-permission configuration are exposed through management APIs; `code` and `is_system` are immutable there, and `super_admin` keeps dynamic permission expansion (no stored grants).

## Permission

Implemented in Phase 2A. `Permission` is a stable backend capability, such as `system:user:create`.

Fields:

- `id`
- `code` (`<namespace>:<resource>:<action>`, unique, no entity IDs)
- `name`
- `kind` (`action`; `workspace`/`menu` are reserved model values with no seeded data — there is no `data_scope` kind because scope is role policy)
- `module`
- `description`
- `status` (`active` / `disabled`; sync disables catalog-removed codes instead of deleting)
- timestamp fields

Permission definitions are a code-owned catalog (`app/modules/rbac/catalog.py`) mirrored by the explicit `sync-permissions` CLI; the database controls which roles hold them, never whether a protected backend dependency checks them.

## RolePermission

Implemented in Phase 2A. Maps roles to permissions.

- composite PK (`role_id`, `permission_id`), both FK `ON DELETE RESTRICT`
- `created_at`

The pair is unique by construction; grants are never cascaded away.

## UserRole

Implemented in Phase 2A. Maps users to roles.

- `id`
- `user_id` / `role_id` (FK `ON DELETE RESTRICT`, unique pair)
- `assigned_by` (acting administrator; evidence, not an authorization input)
- `assigned_at`
- timestamp fields

A user may hold multiple roles. Effective action permission is the union of permission codes from all active, non-deleted roles whose active grants point at active permissions, deduplicated. A user holding the `super_admin` system role resolves to every active permission (dynamic expansion — no username/id bypass). Validity windows (`valid_from`/`valid_to`) stay deferred until a product requirement asks for temporary roles.

## Workspace

Implemented in Phase 3A. `Workspace` is a first-class product area, not merely a menu folder — and not a backend domain module. Which workspaces may exist is decided by the code-owned `Workspace Registry` (`app/modules/workspaces/registry.py`); the database mirrors it via `sync-workspaces` and stores operational state.

Fields: `id`, `name`, `code`, `icon`, `description`, `home_path`, `sort`, `status` (`active`/`disabled`), `deleted_at`, timestamps.

Rules:

- `code` is a stable software identifier, unique for the workspace's full lifetime (soft-deleted rows keep occupying it).
- **Department ≠ Workspace** and **Workspace ≠ backend domain**: a backend module is never created just because a workspace directory exists.
- **System Management is platform capability, never a business workspace**; platform administration keeps its own routes and `system:*` permission codes.
- Workspace access is expressed only as the `workspace:<code>:access` permission (kind `workspace`), derived deterministically from the registry into the permission catalog. It reaches users only via `UserRole → Role → RolePermission`.

## WorkspaceDepartment

Implemented in Phase 3A. Pure many-to-many association between a workspace and departments the product associates with it.

Fields: `workspace_id` (composite PK), `department_id` (composite PK), `created_at`. There is deliberately no `is_default` column — no product consumer exists.

This association describes product/organizational association only. **It is not an access grant**: department membership never implies workspace access; users still need a role carrying `workspace:<code>:access`.

## Menu

Implemented in Phase 3A. `Menu` is navigation metadata inside one workspace — directories and pages only. Button-level visibility belongs to frontend `hasPermission` checks, never to menu rows (the `action` menu type from early drafts was dropped deliberately).

Fields: `id`, `workspace_id`, `parent_id` (adjacency list), `code` (unique per workspace, full-lifetime stable), `name`, `menu_type` (`directory`, `page`), `route_path` (workspace-relative), `component_key` (stable key resolved by the frontend component registry — never a raw import path), `icon`, `permission_code`, `sort`, `visible`, `status` (`active`/`disabled`), `deleted_at`, timestamps.

Rules:

- Menus form a tree constrained to one workspace; self-parent and moving under a descendant are rejected (recursive CTE in `MenuService`).
- `permission_code` is optional UI-visibility metadata and must reference an active code-owned catalog permission (unknown or disabled codes are rejected at the service boundary).
- **Menu visibility is not authorization**: backend authorization always answers through `require_permission(...)`/`AuthorizationService`, never through menu data.

## Announcement

`Announcement` is a scoped communication record.

Planned fields:

- `id`
- `title`
- `content`
- `content_format` (`markdown` or `html` after sanitization policy is defined)
- `announcement_type`
- `status` (`draft`, `published`, `withdrawn`)
- `is_pinned`
- `published_at`
- `expires_at`
- audit fields

## AnnouncementScope

Defines recipients as one of:

- all company users;
- departments;
- roles;
- explicit users.

The precise normalized tables will be defined during implementation. The model must preserve the exact scope at publication time because role/department membership changes later must not rewrite history.

## AuditLog

`AuditLog` is append-only evidence.

Planned fields:

- `id`
- `operator_id`
- `operator_name`
- `module`
- `action`
- `target_type`
- `target_id`
- `request_method`
- `request_path`
- `request_ip`
- `user_agent`
- `result`
- `duration_ms`
- `before_snapshot` / `after_snapshot`, when justified
- `created_at`

Rules:

- Audit records are never updated or deleted by application CRUD.
- Sensitive fields are masked before persistence.
- Audit failure must not silently erase authorization evidence.

## RefreshToken

Implemented in Phase 1B. Stores server-side token lineage and revocation state for authenticated sessions.

Fields:

- `id`
- `session_id` (groups the rotation family)
- `user_id`
- `token_hash` (SHA-256 of the opaque token; raw value exists only in the browser cookie)
- `issued_at`
- `expires_at`
- `revoked_at`
- `replaced_by_id`
- `user_agent` / `ip`

Only a secure hash of the refresh token is stored. Rotation happens in one transaction with a row lock; presenting any rotated or revoked token revokes the whole `session_id` family and marks the session revoked in Redis. `client_id` is deferred until a second client type exists.

## LoginLog

Implemented in Phase 1B. Records authentication attempts separately from administrative audit.

Fields:

- `id`
- `username` (as submitted, even for unknown users)
- `user_id` when identified
- `result` (`success` / `failure` / `rate_limited`)
- `failure_reason`
- `ip`
- `user_agent`
- `created_at`

It supports brute-force detection and security review without becoming a general audit log. Writes go through an independent session so request rollbacks cannot erase authentication evidence.
