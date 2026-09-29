# Product Scope

## Product Intent

TMT Workspace is the unified entry point for internal company systems. It is not a traditional admin dashboard with one implicit system; it is a platform where independently scoped workspaces can be introduced without weakening shared identity, permission, organization, navigation, and audit foundations.

Current product name: **TMT Workspace**.

## Platform Concepts

- **User**: an employee account, retained after resignation or administrative deactivation.
- **Department**: an organization tree independent of authorization roles.
- **Position**: a job/position concept independent of system permissions.
- **Role**: a named authorization bundle.
- **Permission**: a stable backend-enforced capability code.
- **Workspace**: a first-class area such as Operations, Product, Procurement, Warehouse, Customer Service, Finance, HR, Technology, Public, or System Management.
- **Menu**: workspace-aware navigation and UI action metadata.
- **Announcement**: scoped company/system communication.
- **Audit Log**: durable evidence for sensitive administrative operations.

## Phase 0 Scope

Phase 0 is architecture and repository bootstrap only.

Included:

- modular monolith repository layout;
- FastAPI application factory and versioned API convention;
- health/liveness/readiness API;
- typed environment configuration;
- asynchronous SQLAlchemy engine/session foundation;
- canonical response and exception contract;
- Alembic async migration foundation;
- PostgreSQL/Redis local Docker Compose;
- Vue 3 console shell, static routing, application layout, login page skeleton,
  API client boundary, and empty module/workspace directories;
- Ruff, MyPy, Pytest, and validation workflow;
- architecture, RBAC, data scope, database, API, security, testing, workflow, and roadmap documents;
- AI coding rules.

Explicitly excluded from Phase 0:

- login and JWT implementation;
- user, department, position, role, permission, workspace, menu, and announcement CRUD;
- database tables for those entities;
- business modules;
- external integrations;
- AI/LLM features;
- workflow engine;
- Kubernetes;
- event bus;
- dynamic frontend navigation and functional protected views.

## Future Center Model

The platform will expose first-class workspaces, but their implementation remains out of Phase 0:

```text
Home
Operation Center
Product Center
Procurement Center
Supply Chain Center
Warehouse Center
Customer Service Center
Finance Center
HR Center
Technology Center
Public Center
System Management
```

Workspaces must not be hard-wired one-to-one to departments. One workspace may serve many departments, and one department may access multiple workspaces.

## Success Criteria for Phase 0

1. A contributor can understand the platform architecture from documentation without reverse-engineering code.
2. The repository runs with a typed configuration, async database engine, migration tool, and health endpoint.
3. Shared API, error, timestamp, and module-boundary rules are established.
4. Security and permission requirements exist before identity/RBAC implementation.
5. AI agents have an enforceable coding contract and required validation flow.
6. Future modules can be added without redesigning the core.
7. The frontend shell builds successfully and can load the application layout while
   backend-driven navigation remains deferred to later phases.
