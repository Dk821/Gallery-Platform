from typing import Any

from pydantic import BaseModel, Field


def paginate_params(page: int = 1, limit: int = 50) -> tuple[int, int]:
    page = max(page, 1)
    limit = min(max(limit, 1), 200)  # never let the client force an unbounded query
    return page, limit


def build_page(items: list[Any], page: int, limit: int, total: int) -> dict:
    """
    Plain-dict page envelope (deliberately not a Pydantic generic model -
    avoids any ambiguity around unparametrized Generic[T] instances and
    keeps FastAPI's jsonable_encoder path simple for mixed item types
    (dicts here, Pydantic models there)).
    """
    return {
        "items": items,
        "page": page,
        "limit": limit,
        "total": total,
        "has_more": page * limit < total,
    }


class PaginationQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=50, ge=1, le=200)
