"""Central SQLAlchemy model registry.

Import every model module here so Alembic autogenerate can discover metadata
without scanning application internals.
"""

from app.db.base import Base
from app.modules.departments import models as department_models
from app.modules.positions import models as position_models
from app.modules.users import models as user_models

__all__ = ["Base", "department_models", "position_models", "user_models"]
