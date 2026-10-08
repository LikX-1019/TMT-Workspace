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

Static shell routes:

- `/login`;
- `/` home;
- `/profile`;
- catch-all 404.

The router guard runs one `auth.bootstrap()` before its first decision: page reloads restore the session through `POST /auth/refresh` + `GET /auth/me` instead of bouncing to `/login`. Authenticated users are redirected away from `/login`; unauthenticated users are redirected to `/login` from every protected route. Later, `/auth/workspaces` and workspace/menu APIs will provide the data used to compose protected navigation. The frontend must not treat a visible menu as authorization. A missing or denied backend permission always results in a real denial from the API.

## State Policy

Pinia owns session state (`accessToken`, `currentUser`, `authInitialized`) plus the effective `roles`/`permissions` display data from `GET /auth/me`. The `auth.hasPermission(code)` getter lets views hide or disable buttons they know the user cannot use.

**Frontend visibility is UX, never a security boundary.** `hasPermission` exists to avoid rendering actions that will certainly fail with 403; the only enforcement point is the backend `require_permission(...)` dependency. Do not build `v-permission` directives or permission-driven routing on top of it without an explicit product requirement.

The implemented browser token contract is:

- **Access token**: JavaScript runtime memory only (`utils/runtime-token`). It is not written to `localStorage` or `sessionStorage`.
- **Refresh token**: an `HttpOnly`, `SameSite=Lax`, `Secure`-in-production cookie owned by the backend (`Path=/api/v1/auth`). JavaScript never reads it; `withCredentials: true` carries it.
- **Page refresh**: `POST /auth/refresh` restores the authenticated session and returns a fresh access token; `POST /auth/logout` ends it server-side and clears the cookie.

The API client (`src/api/request.ts`) centralizes:

- base URL (`VITE_API_BASE_URL`) and `withCredentials`;
- bearer-token attachment from runtime memory;
- single-flight 401 recovery: on the first 401 (excluding `/auth/login`, `/auth/refresh`, `/auth/logout`) one `POST /auth/refresh` runs, all concurrent waiters share the new token, each failing request is retried exactly once, and a failed refresh clears the runtime session and redirects to `/login` (`utils/session-navigation`);
- typed response envelope handling.

`src/api/session-refresh.ts` holds the single-flight coordinator as a pure, unit-tested module; the interceptor only wires it to axios. The frontend still never observes or stores the refresh-token value.

## Module Policy

`src/modules/system/<feature>/` contains administrative views such as users, departments, roles, menus, and audit — System Management is platform capability and never a business workspace. `src/modules/public/<feature>/` contains shared employee-facing modules. `src/workspaces/<workspace>/` contains workspace entry views and workspace-local components.

The canonical workspace codes are fixed by the backend registry (`app/modules/workspaces/registry.py`): `operation`, `product`, `procurement`, `warehouse`, `customer-service`, `finance`, `hr`, `tech`. The former `purchase` placeholder directory was renamed to `procurement` in Phase 3A; `purchase` must not be reintroduced. These directories remain placeholders — no workspace UI is implemented yet.

Frontend workspace names are navigation containers only. They do not define backend module names. A workspace view may call multiple backend capability APIs such as products, orders, inventory, or reports. Future workspace URLs compose as `/w/<workspace-code>/<menu route_path>`; menu `route_path` stays workspace-relative, and `component_key` resolves through a code-owned frontend component registry (the backend never supplies import paths).

Modules may import shared layout/API/store/type facilities. They must not import another module's private components or internal composables. When two modules need the same behavior, promote it explicitly to `components/`, `stores/`, `utils/`, or an API contract.

## Build And Verification

```bash
npm --prefix frontend install
npm --prefix frontend run build   # vue-tsc + vite build
npm --prefix frontend run test    # vitest run (Makefile: make test-frontend)
```

The build runs `vue-tsc` before Vite, so type errors block delivery. Dynamic workspace modules require backend permission and data-scope tests before any protected view is exposed.
