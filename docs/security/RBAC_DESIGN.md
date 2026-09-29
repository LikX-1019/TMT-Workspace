# RBAC Design

## Objective

The platform uses role-based access control to separate three questions:

1. Who is the authenticated employee?
2. Which roles does that employee hold?
3. What capabilities and data ranges do those roles enable?

Frontend menu rendering is a UX convenience. Every protected operation is enforced by backend dependencies and service/repository boundaries.

## Core Relationships

```text
User
 --> UserRole --> Role
                   --> RolePermission --> Permission
                   --> DataScopePolicy

Workspace --> Menu --> Permission
Workspace <-> Department
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

Initial planned system roles:

| Role code | Intended use |
| --- | --- |
| `super_admin` | Break-glass platform administration; audit all sensitive actions |
| `system_admin` | Normal platform administration without unrestricted future business powers |
| `security_auditor` | Read-only audit/security administration |
| `workspace_viewer` | Baseline authenticated workspace/navigation access for testing |

Business workspaces define their own roles, for example `operation_operator`, `operation_manager`, `procurement_operator`, or `warehouse_viewer`. Roles should express responsibility, not individual people or departments.

Role rules:

- Role code is immutable once permissions or integrations reference it.
- A system role cannot be deleted while users or required platform workflows depend on it.
- Role modifications require audit records.
- A role should be small enough to reason about; do not create one role per person.

## Assignment Rules

Phase 2:

- Users receive roles only through `user_roles`.
- No direct user-to-permission table is implemented.
- One user may receive multiple roles.

Later extension:

- Temporary role assignment windows;
- delegated administration;
- emergency elevation with expiry and enhanced audit.

These are additive to `user_roles`; they must not permit a hidden bypass of role resolution.

## Authorization Flow

For every protected request:

1. Resolve authenticated user from access-token validation and active session state.
2. Reject disabled, locked, resigned, or soft-deleted users.
3. Load active roles and permissions.
4. Check workspace permission if the route belongs to a workspace.
5. Check action permission.
6. Resolve role data-scope policy and construct an explicit data context.
7. Apply scope at query or mutation time.
8. Audit the operation when it is sensitive.

A request that fails action permission returns `403`; a request that is authenticated but lacks a valid token returns `401`. A resource outside the allowed scope should normally return `404` to avoid confirming existence, unless product/security explicitly requires `403`.

## Dynamic Menu Contract

The authenticated navigation API will derive menus from:

1. workspaces the user may access;
2. active menus in those workspaces;
3. menu type and parent/child relationships;
4. permission codes the user actually holds;
5. visible/status/sort metadata.

Menus may be cached, but cache invalidation must occur when menus, roles, permissions, or user-role assignments change. The API must still verify permissions per request; it must not rely on cache age as an authorization boundary.

## Initial Bootstrap

The first identity implementation must provide an explicit bootstrap path for:

- creating the initial super administrator from environment-provided credentials;
- seeding permission definitions from code;
- creating system roles;
- binding platform permissions to system roles.

The initial password must not be committed. The command should be idempotent enough for infrastructure bootstrapping while remaining safe and audited in production.

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
