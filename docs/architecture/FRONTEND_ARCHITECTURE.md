# Frontend Architecture

## Application Shape

The console lives in `frontend/` and uses Vue 3, TypeScript, Vite, Pinia, Vue Router, Element Plus, and Axios. It is an operational workstation shell, not a marketing site.

```text
frontend/src/api/        # Axios instance and typed backend contracts
frontend/src/layouts/    # Application shell
frontend/src/router/     # Shell routes; dynamic routes arrive from backend contracts
frontend/src/stores/     # Authentication/session state
frontend/src/modules/    # System and public feature modules
frontend/src/workspaces/ # Department workspace entry points
frontend/src/views/      # Login, home, profile, and error shells
```

## Route Policy

Phase 0 contains only static shell routes:

- `/login`;
- `/` home;
- `/profile`;
- catch-all 404.

Later, `/auth/me`, `/auth/workspaces`, and workspace/menu APIs will provide the data used to compose protected navigation. The frontend must not treat a visible menu as authorization. A missing or denied backend permission always results in a real denial from the API.

## State Policy

Pinia owns session state, current user, effective roles/permissions, workspace access, and later UI preferences. Token material stays in storage chosen by Phase 1 security work and is attached through the Axios request interceptor. Components do not read or write raw token storage directly.

The current API client centralizes:

- base URL (`VITE_API_BASE_URL`);
- bearer-token attachment;
- 401 session cleanup;
- typed response envelope handling.

Refresh-token rotation will use the same client boundary once the backend contract is implemented.

## Module Policy

`src/modules/system/<feature>/` contains administrative views such as users, departments, roles, menus, and audit. `src/modules/public/<feature>/` contains shared employee-facing modules. `src/workspaces/<workspace>/` contains workspace entry views and workspace-local components.

Modules may import shared layout/API/store/type facilities. They must not import another module's private components or internal composables. When two modules need the same behavior, promote it explicitly to `components/`, `stores/`, `utils/`, or an API contract.

## Build And Verification

```bash
npm --prefix frontend install
npm --prefix frontend run build
```

The build runs `vue-tsc` before Vite, so type errors block delivery. Dynamic workspace modules require backend permission and data-scope tests before any protected view is exposed.

