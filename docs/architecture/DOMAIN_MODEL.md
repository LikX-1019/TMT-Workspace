# Domain Model

Phase 1A implements the organization and identity persistence foundation. Authentication, RBAC, workspaces, and audit remain future contracts and must not be inferred from these tables.

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

Planned and explicitly deferred:

```text
User --- UserRole --- Role --- RolePermission --- Permission
 |                       |
 |                       +--- DataScopePolicy

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
- Password hashing and login credentials are deferred to Phase 1B, likely as a separate local credential model.
- A resigned employee remains queryable for historical and audit purposes.
- `account_status=disabled` blocks login and API access even if roles remain assigned.
- Role assignment is through `user_roles`; direct user-permission grants are not part of the initial platform.
- Organization membership is not stored only as free text on the user row.

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

`Role` is a named authorization bundle, for example `System Administrator`, `HR Operator`, or `Workspace Viewer`.

Planned fields:

- `id`
- `name`
- `code`
- `description`
- `data_scope_type`
- `sort`
- `status`
- `is_system`
- `deleted_at`
- timestamp/audit fields

Rules:

- System roles cannot be deleted.
- Role code is stable; display names are not used as identifiers.
- A role may carry a data-scope policy, but data scope does not replace action permission.

## Permission

`Permission` is a stable backend capability, such as `system:user:create`.

Planned fields:

- `id`
- `code`
- `name`
- `kind` (`workspace`, `menu`, `action`, `data_scope`)
- `module`
- `description`
- `status`
- unique constraint on `code`

Permission definitions may be seeded from code. Database configuration controls which roles hold them, not whether a protected backend dependency checks them.

## RolePermission

Maps roles to permissions.

Planned fields:

- `role_id`
- `permission_id`
- audit fields where useful

The pair `(role_id, permission_id)` is unique.

## UserRole

Maps users to roles.

Planned fields:

- `user_id`
- `role_id`
- `assigned_by`
- `assigned_at`
- optional `valid_from` / `valid_to`

A user may hold multiple roles. Effective action permission is the union of permissions from all active, non-deleted roles.

## Workspace

`Workspace` is a first-class product area, not merely a menu folder.

Planned fields:

- `id`
- `name`
- `code`
- `icon`
- `description`
- `home_path`
- `sort`
- `status`
- timestamp/audit fields

Rules:

- `code` is stable and unique.
- System Management is a workspace so platform administration uses the same navigation and authorization concepts.
- Workspace access requires both a workspace permission and, where applicable, a role/data-scope relationship.

## WorkspaceDepartment

Many-to-many association between a workspace and departments that are authorized or associated with it.

Planned fields:

- `workspace_id`
- `department_id`
- `is_default`
- timestamp/audit fields where useful

This association describes product/organizational association. It does not automatically grant users access; users still need an authorized role and workspace permission.

## Menu

`Menu` represents directories, pages, and UI actions inside a workspace.

Planned fields:

- `id`
- `parent_id`
- `workspace_id`
- `name`
- `menu_type` (`directory`, `page`, `action`)
- `route`
- `component`
- `icon`
- `permission_code`
- `sort`
- `visible`
- `status`
- timestamp/audit fields

Rules:

- Menus form a tree constrained to one workspace.
- Backend authorization uses the referenced permission code, not menu visibility.
- A menu action may represent a visible button, but it is not a substitute for a real backend permission check.

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

Stores server-side token lineage and revocation state for authenticated sessions.

Planned fields include:

- `id`
- `user_id`
- `token_hash`
- `issued_at`
- `expires_at`
- `revoked_at`
- `replaced_by_id`
- `client_id` / `user_agent` / `ip`

Only a secure hash of the refresh token is stored.

## LoginLog

`LoginLog` records authentication attempts separately from administrative audit.

Planned fields include:

- `id`
- `username`
- `user_id` when identified
- `result`
- `failure_reason`
- `ip`
- `user_agent`
- `created_at`

It supports brute-force detection and security review without becoming a general audit log.
