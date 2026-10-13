from collections.abc import Callable
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.core.deps import Allow, DbDep
from app.core.pagination import Page, PageParamsDep
from app.modules.inventory import service
from app.modules.inventory.models import StockAdjustment, StockCount, StockTransfer
from app.modules.inventory.schemas import (
    AdjustmentIn,
    AdjustmentOut,
    CountIn,
    CountOut,
    CountPostOut,
    LedgerPage,
    StockPage,
    TransferIn,
    TransferOut,
)

router = APIRouter(prefix="/inventory", tags=["inventory"])

StatusFilter = Literal["draft", "pending_approval", "posted", "cancelled"]


@router.get("/stock")
def list_stock(
    db: DbDep,
    params: PageParamsDep,
    _: Allow("stock.view"),
    warehouse_id: int | None = None,
    product_id: int | None = None,
    category_id: int | None = None,
    product_type: Literal["raw_material", "finished_good", "trading"] | None = None,
    low_stock: bool = False,
) -> StockPage:
    return StockPage(
        **service.list_stock(
            db, params, warehouse_id, product_id, category_id, product_type, low_stock
        )
    )


@router.get("/ledger")
def stock_ledger(
    db: DbDep,
    params: PageParamsDep,
    _: Allow("stock.view"),
    product_id: int,
    warehouse_id: int | None = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> LedgerPage:
    return LedgerPage(
        **service.stock_ledger(db, params, product_id, warehouse_id, date_from, date_to)
    )


def _document_routes(
    path: str,
    perm: str,
    model: Any,
    label: str,
    schema_in: type[BaseModel],
    schema_out: type[BaseModel],
    create: Callable[..., Any],
    post: Callable[..., Any],
    cancel: Callable[..., Any],
    post_out: type[BaseModel] | None = None,
) -> None:
    """create / list / detail / post / cancel for one stock document type.
    Permissions: view, create; post = `.edit`; cancel = `.delete`."""
    post_model = post_out or schema_out

    @router.post(path, status_code=201, name=f"create_{perm}")
    def create_(
        data: schema_in, db: DbDep, user: Allow(f"{perm}.create"), request: Request
    ) -> schema_out:
        return schema_out(**service.document_detail(db, create(db, user, data, request)))

    @router.get(path, name=f"list_{perm}")
    def list_(
        db: DbDep,
        params: PageParamsDep,
        _: Allow(f"{perm}.view"),
        status: StatusFilter | None = None,
        warehouse_id: int | None = None,
    ) -> Page[schema_out]:
        return Page[schema_out](**service.document_list(db, model, params, status, warehouse_id))

    @router.get(f"{path}/{{doc_id}}", name=f"get_{perm}")
    def get_(doc_id: int, db: DbDep, _: Allow(f"{perm}.view")) -> schema_out:
        return schema_out(
            **service.document_detail(db, service.get_document(db, model, doc_id, label))
        )

    @router.post(f"{path}/{{doc_id}}/post", name=f"post_{perm}")
    def post_(doc_id: int, db: DbDep, user: Allow(f"{perm}.edit"), request: Request) -> post_model:
        result = post(db, doc_id, user, request)
        if post_out is not None:
            doc, moved = result
            return post_out(**service.document_detail(db, doc), moved_since_snapshot=moved)
        return schema_out(**service.document_detail(db, result))

    @router.post(f"{path}/{{doc_id}}/cancel", name=f"cancel_{perm}")
    def cancel_(
        doc_id: int, db: DbDep, user: Allow(f"{perm}.delete"), request: Request
    ) -> schema_out:
        return schema_out(**service.document_detail(db, cancel(db, doc_id, user, request)))


_document_routes(
    "/transfers",
    "stock_transfer",
    StockTransfer,
    "Transfer",
    TransferIn,
    TransferOut,
    service.create_transfer,
    service.post_transfer,
    service.cancel_transfer,
)
_document_routes(
    "/adjustments",
    "stock_adjustment",
    StockAdjustment,
    "Adjustment",
    AdjustmentIn,
    AdjustmentOut,
    service.create_adjustment,
    service.submit_adjustment,
    service.cancel_adjustment,
)
_document_routes(
    "/counts",
    "stock_count",
    StockCount,
    "Count",
    CountIn,
    CountOut,
    service.create_count,
    service.post_count,
    service.cancel_count,
    post_out=CountPostOut,
)
