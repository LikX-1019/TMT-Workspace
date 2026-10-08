"""Role-based access control: persistence, catalog sync, and authorization.

Phase 2A scope:

- ``models``: roles, permissions, user_roles, role_permissions;
- ``catalog``: the code-owned permission/system-role contract;
- ``repository``: persistence and set-based resolution queries;
- ``service``: role lifecycle rules, catalog synchronization, and the
  ``AuthorizationService`` that answers "what can this user do?".

Enforcement dependencies (``require_permission``) arrive in Phase 2B;
workspace authorization arrives in Phase 3; data-scope query enforcement is
deferred to a dedicated later phase.
"""
