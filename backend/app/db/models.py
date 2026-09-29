"""Central SQLAlchemy model registry.

Import every model module here so Alembic autogenerate can discover metadata
without scanning application internals.
"""

from app.db.base import Base

__all__ = ["Base"]
