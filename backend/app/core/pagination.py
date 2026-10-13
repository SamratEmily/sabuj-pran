from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


@dataclass
class PageParams:
    page: int = 1
    page_size: int = 20
    search: str | None = None

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_params(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> PageParams:
    return PageParams(page=page, page_size=page_size, search=(search or "").strip() or None)


PageParamsDep = Annotated[PageParams, Depends(page_params)]


def paginate(db: Session, stmt: Select[Any], params: PageParams) -> dict[str, Any]:
    """Run `stmt` for one page. Returns a dict matching `Page`."""
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = db.scalars(stmt.limit(params.page_size).offset(params.offset)).all()
    return {
        "items": list(items),
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
    }
