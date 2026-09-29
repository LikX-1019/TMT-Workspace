# Coding Standards

## Toolchain

| Tool | Purpose |
| --- | --- |
| Python 3.12+ | Runtime baseline |
| uv | Dependency and virtual-environment management |
| Ruff format | Deterministic formatting |
| Ruff lint | Fast Python lint rules |
| MyPy strict | Static typing |
| Pytest | Unit/API/integration testing |
| Alembic | Database migrations |

Required validation:

```bash
make check
```

Individual commands:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

## Formatting

Ruff format is authoritative. Do not hand-format around it. Use a 100-character line limit and sorted imports.

## Typing

- All public functions/classes are annotated.
- Avoid bare `dict`, `list`, or untyped `Any`.
- Prefer precise domain types and `Literal`/enums for closed sets.
- Use `X | None` instead of `Optional[X]`.
- Use `datetime` with timezone-aware UTC values.
- Do not silence MyPy with blanket ignores unless an external-library boundary genuinely requires it. Record the reason when unavoidable.

## Naming

| Element | Convention | Example |
| --- | --- | --- |
| Package/module | lowercase snake_case | `user_roles` |
| Class | PascalCase | `UserService` |
| Function/method | lowercase snake_case | `get_by_workspace` |
| Constant | UPPER_SNAKE_CASE | `MAX_PAGE_SIZE` |
| Enum value | lowercase snake_case for Python, uppercase serialized value | `DataScopeType.ALL` |
| Permission code | lowercase colon-delimited | `system:user:create` |
| Table/column | lowercase snake_case | `user_roles` / `role_id` |

Avoid `manager`, `helper`, `util`, `common`, `data`, `info`, and `handler` as names unless the abstraction is genuinely clear.

## Async

- FastAPI endpoints and database repositories are async.
- Use `AsyncSession` consistently.
- Do not use blocking database drivers, `requests`, `time.sleep`, or synchronous file I/O in async request paths.
- Keep transactions short and avoid awaiting external APIs while holding a row lock unless the design explicitly documents the compensation/timeout policy.
- Use `anyio.to_thread` or a task system for unavoidable blocking work rather than mixing driver styles.

## Error Handling

- Expected business failures derive from `AppError`.
- Raise specific subclasses such as `AuthenticationError`, `AuthorizationError`, `NotFoundError`, `ConflictError`, or `ValidationError`.
- API handlers do not manually format these errors.
- Preserve context when wrapping unexpected errors; do not swallow the cause.
- Do not use broad `except Exception` except at a documented boundary.
- Error messages are safe for clients; internal diagnostics belong in logs.

## Logging

Use structured logging when application logging is introduced. Log intent and state, not secrets.

Never log:

- passwords or password hashes;
- full tokens or refresh tokens;
- raw Authorization headers;
- production database URLs with credentials;
- unmasked personal/sensitive data;
- full request bodies for authentication or sensitive operations.

Include request ID, user ID when authenticated, module, action, target ID, and outcome where relevant.

## Dependencies

- Add a dependency only when it removes real complexity or provides maintained security/business behavior.
- Prefer a small, well-maintained library over a broad framework.
- Pin ranges in `pyproject.toml` and commit `uv.lock`.
- Review licenses and transitive risk before adopting database, crypto, content-rendering, or AI libraries.
- Do not add modules for one trivial function.

## Configuration

- Use `Settings` and the `TMT_` prefix.
- No magic environment reads scattered through modules.
- No secrets in source, tests, docs, command examples, or Docker image layers.
- Every new setting has a safe default for local development and explicit production policy.

## Comments And Documentation

Comments explain why a decision or invariant exists. Do not narrate obvious assignments. Public contracts, security-sensitive behavior, transaction boundaries, and compatibility guarantees deserve docstrings or documentation.

Update `ARCHITECTURE.md`, domain/database/RBAC/data-scope/API/security docs in the same change when behavior changes.

## Code Review Checklist

- Does the change respect module boundaries?
- Are API request/response schemas and status codes correct?
- Is authorization checked for every protected path?
- Is data scope fail-closed?
- Do database changes include a reviewed migration?
- Are indexes/constraints appropriate?
- Are success/error shapes stable?
- Are tests meaningful, including denial paths?
- Does `make check` pass?
- Are docs and AI rules still accurate?

