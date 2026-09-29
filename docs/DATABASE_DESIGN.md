# Database Design

## Database Conventions

### Engine and connection

- PostgreSQL 16 is the source of truth.
- SQLAlchemy 2.x uses `AsyncSession` and `asyncpg`.
- Alembic uses the same async URL.
- Every request receives one injected session; the default flow commits on success and rolls back on exception.

### Identifiers

- Core platform entities use UUID primary keys.
- Association tables use composite primary keys unless they need lifecycle/audit fields, in which case they use a UUID primary key plus a unique constraint.
- Stable business codes such as `departments.code`, `roles.code`, `permissions.code`, and `workspaces.code` have unique constraints.

### Timestamps

- All database timestamps use PostgreSQL `TIMESTAMPTZ`.
- Application datetimes are timezone-aware UTC.
- Shared `created_at` and `updated_at` use the `TimestampMixin`.
- `created_by`/`updated_by` are added to configuration-like entities where knowing the actor has durable value. Pure association tables do not need them unless assignment history is a product requirement.

### Naming

SQLAlchemy uses this metadata naming convention:

```text
pk_<table>
fk_<table>_<column>_<referenced_table>
uq_<table>_<column>
ck_<table>_<constraint_name>
ix_<table>_<column>
```

Tables use lowercase plural snake_case names. Columns use lowercase snake_case.

### Soft delete

Users, departments, roles, and menus use nullable `deleted_at` when historical integrity matters. Lifecycle fields such as `status` describe active/disabled/published/etc., not deletion.

Rules:

- Soft-deleted rows are excluded from default application queries and unique checks must account for active rows as required by business semantics.
- Audit evidence and login history are never deleted.
- Announcements are withdrawn rather than deleted.
- Physical delete is allowed only for transient technical rows or data explicitly classified as removable by law/product.

## Planned Core Tables

These tables are intentionally not created in Phase 0. They define the contract for Phase 1 and later.

### users

Key columns:

- `id UUID PK`
- `employee_no VARCHAR UNIQUE`
- `username VARCHAR UNIQUE`
- `password_hash VARCHAR NOT NULL`
- `name VARCHAR NOT NULL`
- `email VARCHAR NULL UNIQUE`
- `mobile VARCHAR NULL UNIQUE`
- `avatar_url VARCHAR NULL`
- `employment_status VARCHAR NOT NULL`
- `account_status VARCHAR NOT NULL`
- `primary_supervisor_id UUID NULL FK users.id`
- `last_login_at TIMESTAMPTZ NULL`
- `deleted_at TIMESTAMPTZ NULL`
- `created_at/updated_at`

Indexes:

- unique on `username`;
- unique partial indexes for `email` and `mobile` where not null;
- unique on `employee_no`;
- index on `account_status`;
- index on `department membership` through the assignment table.

### departments

Key columns:

- `id UUID PK`
- `parent_id UUID NULL FK departments.id`
- `name VARCHAR NOT NULL`
- `code VARCHAR NOT NULL`
- `leader_id UUID NULL FK users.id`
- `sort INTEGER NOT NULL`
- `status VARCHAR NOT NULL`
- `deleted_at TIMESTAMPTZ NULL`
- `created_at/updated_at`

Constraints/indexes:

- unique active department code;
- index on `parent_id`;
- index on `status`;
- application/database check preventing self-parent.

### department_closure

Key columns:

- `ancestor_id UUID FK departments.id`
- `descendant_id UUID FK departments.id`
- `depth INTEGER NOT NULL`
- composite PK `(ancestor_id, descendant_id)`
- indexes on both foreign keys

Each department also has a depth-zero self row.

### positions

Key columns:

- `id UUID PK`
- `name VARCHAR NOT NULL`
- `code VARCHAR UNIQUE`
- `description VARCHAR NULL`
- `sort INTEGER NOT NULL`
- `status VARCHAR NOT NULL`
- timestamp fields

### user_department_assignments

Key columns:

- `id UUID PK`
- `user_id UUID FK users.id`
- `department_id UUID FK departments.id`
- `is_primary BOOLEAN NOT NULL`
- `valid_from TIMESTAMPTZ`
- `valid_to TIMESTAMPTZ NULL`
- timestamp/audit fields

Constraints:

- unique `(user_id, department_id, valid_from)` or equivalent history constraint;
- partial unique current primary assignment per user.

### user_positions

Key columns:

- `id UUID PK`
- `user_id UUID FK users.id`
- `position_id UUID FK positions.id`
- `is_primary BOOLEAN NOT NULL`
- `valid_from TIMESTAMPTZ`
- `valid_to TIMESTAMPTZ NULL`

### roles

Key columns:

- `id UUID PK`
- `name VARCHAR NOT NULL`
- `code VARCHAR UNIQUE`
- `description VARCHAR NULL`
- `data_scope_type VARCHAR NOT NULL`
- `sort INTEGER NOT NULL`
- `status VARCHAR NOT NULL`
- `is_system BOOLEAN NOT NULL`
- `deleted_at TIMESTAMPTZ NULL`
- timestamp fields

### permissions

Key columns:

- `id UUID PK`
- `code VARCHAR UNIQUE`
- `name VARCHAR NOT NULL`
- `kind VARCHAR NOT NULL`
- `module VARCHAR NOT NULL`
- `description VARCHAR NULL`
- `status VARCHAR NOT NULL`
- timestamp fields

### role_permissions

Key columns:

- `role_id UUID FK roles.id`
- `permission_id UUID FK permissions.id`
- composite PK `(role_id, permission_id)`

### user_roles

Key columns:

- `id UUID PK`
- `user_id UUID FK users.id`
- `role_id UUID FK roles.id`
- `assigned_by UUID NULL FK users.id`
- `assigned_at TIMESTAMPTZ NOT NULL`
- optional validity window

Constraints:

- unique current `(user_id, role_id)` assignment;
- indexes on both foreign keys.

### workspaces

Key columns:

- `id UUID PK`
- `name VARCHAR NOT NULL`
- `code VARCHAR UNIQUE`
- `icon VARCHAR NULL`
- `description VARCHAR NULL`
- `home_path VARCHAR NULL`
- `sort INTEGER NOT NULL`
- `status VARCHAR NOT NULL`
- timestamp fields

### workspace_departments

Key columns:

- `workspace_id UUID FK workspaces.id`
- `department_id UUID FK departments.id`
- `is_default BOOLEAN NOT NULL`
- composite PK `(workspace_id, department_id)`

### menus

Key columns:

- `id UUID PK`
- `parent_id UUID NULL FK menus.id`
- `workspace_id UUID FK workspaces.id`
- `name VARCHAR NOT NULL`
- `menu_type VARCHAR NOT NULL`
- `route VARCHAR NULL`
- `component VARCHAR NULL`
- `icon VARCHAR NULL`
- `permission_code VARCHAR NULL`
- `sort INTEGER NOT NULL`
- `visible BOOLEAN NOT NULL`
- `status VARCHAR NOT NULL`
- `deleted_at TIMESTAMPTZ NULL`
- timestamp fields

Indexes/constraints:

- index `(workspace_id, parent_id, sort)`;
- foreign key or consistency validation against `permissions.code`;
- directory/page/action-specific validation at service or constraint level.

### announcements

Key columns:

- `id UUID PK`
- `title VARCHAR NOT NULL`
- `content TEXT NOT NULL`
- `content_format VARCHAR NOT NULL`
- `announcement_type VARCHAR NOT NULL`
- `status VARCHAR NOT NULL`
- `is_pinned BOOLEAN NOT NULL`
- `published_at TIMESTAMPTZ NULL`
- `expires_at TIMESTAMPTZ NULL`
- `created_by UUID FK users.id`
- `updated_by UUID NULL FK users.id`
- timestamp fields

Indexes:

- `(status, published_at DESC)`;
- `(is_pinned, published_at DESC)`;
- `expires_at` where not null.

### announcement scopes

Implementation options:

1. one table with `scope_type` and nullable target IDs;
2. separate department/role/user scope tables.

The implementation must prevent an invalid combination such as a department ID attached to an all-company announcement. A typed set of normalized child tables is preferred unless a clearly constrained single-table design is simpler for UI/administration.

### audit_logs

Key columns:

- `id UUID PK`
- `operator_id UUID NULL FK users.id`
- `operator_name VARCHAR NOT NULL`
- `module VARCHAR NOT NULL`
- `action VARCHAR NOT NULL`
- `target_type VARCHAR NULL`
- `target_id VARCHAR NULL`
- `request_method VARCHAR`
- `request_path VARCHAR`
- `request_ip INET`
- `user_agent TEXT`
- `result VARCHAR NOT NULL`
- `duration_ms INTEGER`
- `before_snapshot JSONB NULL`
- `after_snapshot JSONB NULL`
- `created_at TIMESTAMPTZ NOT NULL`

Indexes:

- `(operator_id, created_at DESC)`;
- `(module, action, created_at DESC)`;
- `(target_type, target_id, created_at DESC)`;
- `created_at` for retention/reporting.

`updated_at` is intentionally omitted because audit rows are immutable.

### refresh_tokens

Key columns:

- `id UUID PK`
- `user_id UUID FK users.id`
- `token_hash VARCHAR UNIQUE`
- `issued_at TIMESTAMPTZ`
- `expires_at TIMESTAMPTZ`
- `revoked_at TIMESTAMPTZ NULL`
- `replaced_by_id UUID NULL FK refresh_tokens.id`
- `client_id VARCHAR NULL`
- `ip INET NULL`
- `user_agent TEXT NULL`

Indexes:

- `(user_id, expires_at)`;
- `token_hash`.

### login_logs

Key columns:

- `id UUID PK`
- `username VARCHAR`
- `user_id UUID NULL FK users.id`
- `result VARCHAR NOT NULL`
- `failure_reason VARCHAR NULL`
- `ip INET`
- `user_agent TEXT`
- `created_at TIMESTAMPTZ`

Indexes:

- `(username, created_at DESC)`;
- `(user_id, created_at DESC)`;
- `(ip, created_at DESC)` for brute-force investigation.

## Referential Integrity

Foreign keys are mandatory. `ON DELETE` behavior is explicit:

- core identity/organization references generally use `RESTRICT`;
- owned child rows may use `CASCADE` only when deletion of the parent is a real product behavior;
- soft-deleted parents remain present, so application lifecycle is preferred over database deletion.

## Migration Policy

- Every schema change has a new Alembic revision.
- Autogenerated revisions are reviewed line by line.
- A migration and its downgrade must be intentional; irreversible data migration requires explicit documentation and approval.
- Schema and code changes are deployed with backward-compatible ordering where possible:
  1. add nullable column/table;
  2. backfill;
  3. enforce constraint;
  4. remove old field after all processes are updated.
- Never edit a revision already applied to a shared environment.

## Indexing Strategy

Every foreign key used in a join or lookup is indexed. Add composite indexes only after identifying real query patterns. A typical list endpoint needs indexes for filters, sort, and pagination, for example `(workspace_id, status, published_at DESC)`.

Do not add indexes speculatively to every column; write/query tests and PostgreSQL plans should justify broad changes.

