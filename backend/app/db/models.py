"""Central SQLAlchemy model registry.

Import every model module here so Alembic autogenerate can discover metadata
without scanning application internals.
"""

from app.db.base import Base
from app.modules.auth import models as auth_models
from app.modules.departments import models as department_models
from app.modules.positions import models as position_models
from app.modules.rbac import models as rbac_models
from app.modules.users import models as user_models
from app.modules.workspaces import models as workspace_models

__all__ = [
    "Base",
    "auth_models",
    "department_models",
    "position_models",
    "rbac_models",
    "user_models",
    "workspace_models",
]
