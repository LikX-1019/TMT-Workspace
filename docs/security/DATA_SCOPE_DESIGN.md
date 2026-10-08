# Data Scope Design

## Goal

Action permission decides whether a user can perform a class of operation. Data scope decides which rows that operation can see or affect. The platform must apply both independently; granting `system:user:list` does not imply access to every user row.

Phase 0 designs the mechanism but does not implement business data filters.

## Scope Types

| Type | Meaning |
| --- | --- |
| `ALL` | All rows allowed by the operation and workspace |

> Phase 3A boundary: `workspace_departments` is product/organization metadata.
> It is **not** a data-scope table and **not** an access grant — a user whose
> department is associated with workspace X does not gain workspace X access
> (or any row visibility) from that association. Workspace access comes only
> from `RolePermission → workspace:<code>:access`, and row visibility comes
> only from the role's `data_scope_type` plus (in a later phase)
> `role_data_scope_departments`. No `role_data_scope_departments` table exists
> yet.
| `DEPARTMENT` | Rows belonging to the user's current primary department |
| `DEPARTMENT_AND_CHILDREN` | Primary department and all descendant departments |
| `SELF` | Rows owned by or assigned to the current user |
| `CUSTOM` | Explicit department set assigned to the role/user context |

All comparisons occur against an explicit ownership column. The platform never guesses data ownership from URL IDs or frontend state.

## Scope Context

Authorization middleware will build a typed context after authentication:

```python
@dataclass(frozen=True)
class ScopeContext:
    user_id: UUID
    primary_department_id: UUID | None
    descendant_department_ids: tuple[UUID, ...]
    custom_department_ids: tuple[UUID, ...]
    workspace_id: UUID | None
    scope_type: DataScopeType
```

Rules:

- `descendant_department_ids` is resolved from `departments.parent_id` with a PostgreSQL recursive CTE.
- `custom_department_ids` comes from the role or future user-scope override table.
- If a user has multiple roles, the effective scope is the safest union required by the operation's documented policy. Usually this means the union of non-`ALL` scopes; any `ALL` role grants all allowed rows for that operation.
- A missing department context does not silently become `ALL`.
- The context is immutable for the request.

## Entity Contract

A queryable business entity must explicitly expose the columns needed by scope policy:

```text
workspace_id      # when the resource is workspace-scoped
department_id     # when department scope applies
created_by_id     # when SELF scope applies
assigned_to_id    # when assignment-based SELF scope applies
```

Every module must declare which column represents each concept. The framework should not assume all tables use the same owner column.

## SQLAlchemy Application Strategy

Repositories accept a scope context and apply predicates before executing a query.

Conceptual helper:

```python
class DataScopeFilter:
    def apply(
        self,
        statement: Select[tuple[Any]],
        *,
        workspace_column: ColumnElement[UUID] | None,
        department_column: ColumnElement[UUID] | None,
        owner_column: ColumnElement[UUID] | None,
    ) -> Select[tuple[Any]]: ...
```

Planned mapping:

| Scope | Predicate |
| --- | --- |
| `ALL` | workspace condition only, if applicable |
| `DEPARTMENT` | `department_column == context.primary_department_id` |
| `DEPARTMENT_AND_CHILDREN` | `department_column.in_(context.descendant_department_ids)` from a recursive subtree query |
| `SELF` | `owner_column == context.user_id` or assignment-specific condition |
| `CUSTOM` | `department_column.in_(context.custom_department_ids)` |

This remains explicit repository behavior rather than a global SQL rewriting system. A future policy registry can reduce duplication after enough modules establish their column contracts.

For mutations, the same predicate must appear in `UPDATE`/`DELETE WHERE` clauses or in a locked `SELECT` followed by the mutation inside one transaction. Services must not fetch a row without scope and then authorize it afterward.

## Workspace Scope

Workspace permission and row scope are separate:

1. A user may have `operation:product:list`, giving the action capability.
2. Workspace access may restrict the route to the Operation workspace.
3. A row-level `workspace_id` can further partition data.

If a query is workspace-scoped, the repository must constrain by the current workspace ID before applying department/self rules.

## Department Tree

The organization model uses `departments.parent_id` for adjacency. Descendant lookup uses a PostgreSQL recursive CTE. `department_closure` is a future optimization, not part of the first implementation.

When a department moves:

1. validate that the new parent is not the department itself or one of its descendants;
2. change `parent_id` in one transaction;
3. audit old and new parentage;
4. invalidate relevant data-scope caches.

Data rows generally store the directly owning `department_id`. During historical review, the applicable recursive subtree is resolved at query time unless a documented reporting table intentionally freezes the department path.

## Multiple Roles And Precedence

The initial policy:

- action permissions use union;
- department scopes use union of allowed department IDs;
- `SELF` scope applies only where an operation's owner/assignment column is defined;
- `ALL` grants all rows for that specific operation/workspace.

The effective policy must never be computed by trusting a client-provided scope label. Role resolution happens on the server for every request.

## Custom Scope

`CUSTOM` is backed by explicit department assignments, initially attached to a role policy:

```text
role_data_scope_departments(role_id, department_id)
```

A future `user_data_scope_override` can be added for emergency or delegated access. Overrides must have validity windows, approver fields, and audit records.

## Failure Policy

- Missing required scope column: fail closed and surface an implementation error.
- User without primary department: department scope yields no rows, not all rows.
- Inactive/deleted department: retain historical row linkage but do not grant new scope expansion.
- Role changed during request: request uses the transaction-consistent resolved context; later requests resolve the new role.

## Future Scope Implementation

The first scope implementation should include:

- `DataScopeType` enum;
- typed scope context construction;
- permission dependency plus scope dependency ordering;
- one integration test proving `DEPARTMENT_AND_CHILDREN` cannot read an outside-department row;
- recursive subtree behavior for parent, child, and grandchild departments;
- one integration test proving `SELF` cannot mutate another user's resource.
