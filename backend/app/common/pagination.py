"""Canonical pagination schemas for list APIs."""

from math import ceil

from pydantic import BaseModel, Field


class PageParams(BaseModel):
    """Offset-pagination request parameters."""

    page: int = Field(default=1, ge=1, description="One-based page number")
    page_size: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        """Return the SQL-safe offset for the requested page."""

        return (self.page - 1) * self.page_size


class PageMeta(BaseModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    total_pages: int = Field(ge=0)

    @classmethod
    def build(cls, *, page: int, page_size: int, total: int) -> "PageMeta":
        """Build pagination metadata and avoid negative values for empty sets."""

        return cls(
            page=page,
            page_size=page_size,
            total=total,
            total_pages=ceil(total / page_size) if total else 0,
        )


class Page[T](BaseModel):
    items: list[T]
    meta: PageMeta
