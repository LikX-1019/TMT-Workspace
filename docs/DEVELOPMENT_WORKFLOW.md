# Development Workflow

## Task Flow

Every contributor and AI agent follows the same order:

1. **Read** the affected module, tests, migrations, and documentation.
2. **Understand** existing behavior and contracts before choosing an implementation.
3. **Plan** the smallest safe change, including permission/database/API impact.
4. **Implement** using established patterns.
5. **Test** behavior, denial paths, constraints, and compatibility.
6. **Lint and type check**.
7. **Review the diff** as a whole.
8. **Document** durable architecture, security, and product decisions.

## Environment Setup

```bash
git clone <repository-url>
cd <repository-directory>
make install
cp .env.example .env
make compose-up
make migrate   # once model migrations exist
make dev
```

The current Phase 0 test suite does not require Docker.

## Branching

Use focused branches:

```text
feature/user-module
fix/login-rate-limit
docs/data-scope-policy
chore/ruff-configuration
```

One branch addresses one coherent outcome. Do not mix unrelated refactors, dependency upgrades, and feature work unless the coupling is explicit.

## Commit Discipline

Commit messages should describe behavior, not only file names:

```text
feat: add async database session foundation
fix: fail readiness when database is unavailable
docs: define data scope policy
test: cover health API envelope
```

Before each commit:

1. inspect `git diff`;
2. remove secrets, local paths, debug output, and unrelated churn;
3. ensure generated migrations are intentional;
4. run `make check`.

## Database Changes

1. Update or create module models.
2. Update `docs/DATABASE_DESIGN.md` and RBAC/data-scope docs if relevant.
3. Generate a revision:

```bash
make m="create users and departments" revision
```

4. Review the generated migration by hand.
5. Test upgrade/downgrade against PostgreSQL.
6. Preserve compatibility for deployments that still run the prior process version when necessary.

Do not edit migrations already applied to a shared environment.

## API Changes

1. Define/adjust Pydantic request and response schemas.
2. Add/adjust router and reusable dependencies.
3. Add status-code and error-contract tests.
4. Check generated OpenAPI.
5. Update `docs/API_DESIGN.md`.
6. Preserve stable success/error codes.

## Permission Changes

1. Add the permission code to the module and seed catalog.
2. Update `docs/RBAC_DESIGN.md`.
3. Bind it to intended roles.
4. Add a reusable permission dependency.
5. Add allowed/denied tests.
6. Audit role/permission changes.

Never infer permission from frontend route state.

## AI Agent Requirements

An AI agent must:

- state assumptions when requirements are ambiguous;
- avoid unrelated refactors;
- work with existing patterns rather than introducing a second style;
- report any incomplete validation explicitly;
- not claim Phase completion without files, tests, and command evidence.

AI agents must not create large speculative CRUD modules unless the task explicitly asks for that implementation.

## Definition Of Done

A task is complete only when:

- intended behavior works;
- permissions fail closed;
- database changes are migrated and reviewed;
- API/OpenAPI contracts are consistent;
- tests cover positive and negative paths;
- Ruff, MyPy, and Pytest pass;
- documentation is updated;
- the diff contains no secrets or unrelated changes;
- remaining limitations are reported plainly.

## Incident Or Regression Flow

1. Reproduce with a failing test.
2. Identify the contract that regressed.
3. Fix the behavior at the correct boundary.
4. Add regression tests.
5. Review whether similar endpoints share the defect.
6. Update security/architecture documentation if the root cause was policy-level.

