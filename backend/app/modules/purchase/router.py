from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.core.deps import Allow, DbDep, require_permission
from app.core.pagination import Page, PageParamsDep
from app.modules.purchase import service
from app.modules.purchase.schemas import (
    DirectPurchaseIn,
    PoDetailOut,
    PoIn,
    PoOut,
    PoStatus,
    ReceiptOut,
    ReceiveIn,
    ReturnIn,
    ReturnOut,
)

router = APIRouter(prefix="/purchase", tags=["purchase"])

DateFrom = Annotated[date | None, Query(alias="from")]
DateTo = Annotated[date | None, Query(alias="to")]


def _po(db: DbDep, po_id: int) -> PoDetailOut:
    return PoDetailOut(**service.po_detail(db, service.get_po(db, po_id)))


# --- purchase orders -------------------------------------------------------------------


@router.get("/orders")
def list_orders(
    db: DbDep,
    params: PageParamsDep,
    _: Allow("purchase_order.view"),
    supplier_id: int | None = None,
    status: PoStatus | None = None,
    date_from: DateFrom = None,
    date_to: DateTo = None,
) -> Page[PoOut]:
    return Page[PoOut](**service.list_pos(db, params, supplier_id, status, date_from, date_to))


@router.post("/orders", status_code=201)
def create_order(
    data: PoIn, db: DbDep, user: Allow("purchase_order.create"), request: Request
) -> PoDetailOut:
    return _po(db, service.create_po(db, user, data, request).id)


@router.get("/orders/{po_id}")
def get_order(po_id: int, db: DbDep, _: Allow("purchase_order.view")) -> PoDetailOut:
    return _po(db, po_id)


@router.put("/orders/{po_id}")
def update_order(
    po_id: int, data: PoIn, db: DbDep, user: Allow("purchase_order.edit"), request: Request
) -> PoDetailOut:
    return _po(db, service.update_po(db, user, po_id, data, request).id)


@router.post("/orders/{po_id}/approve")
def approve_order(
    po_id: int, db: DbDep, user: Allow("purchase_order.edit"), request: Request
) -> PoDetailOut:
    return _po(db, service.approve_po(db, user, po_id, request).id)


@router.post("/orders/{po_id}/cancel")
def cancel_order(
    po_id: int, db: DbDep, user: Allow("purchase_order.delete"), request: Request
) -> PoDetailOut:
    return _po(db, service.cancel_po(db, user, po_id, request).id)


@router.post("/orders/{po_id}/receive", status_code=201)
def receive(
    po_id: int, data: ReceiveIn, db: DbDep, user: Allow("goods_receipt.create"), request: Request
) -> ReceiptOut:
    return ReceiptOut(
        **service.receipt_out(db, service.receive_goods(db, user, po_id, data, request))
    )


@router.post("/direct", status_code=201)
def direct(
    data: DirectPurchaseIn,
    db: DbDep,
    user: Allow("goods_receipt.create"),
    request: Request,
    _po_perm: Annotated[object, Depends(require_permission("purchase_order.create"))],
) -> PoDetailOut:
    return _po(db, service.direct_purchase(db, user, data, request).id)


# --- goods receipts & returns ----------------------------------------------------------


@router.get("/receipts")
def list_receipts(
    db: DbDep,
    params: PageParamsDep,
    _: Allow("goods_receipt.view"),
    supplier_id: int | None = None,
    po_id: int | None = None,
    date_from: DateFrom = None,
    date_to: DateTo = None,
) -> Page[ReceiptOut]:
    return Page[ReceiptOut](
        **service.list_receipts(db, params, supplier_id, po_id, date_from, date_to)
    )


@router.get("/receipts/{grn_id}")
def get_receipt(grn_id: int, db: DbDep, _: Allow("goods_receipt.view")) -> ReceiptOut:
    return ReceiptOut(**service.receipt_out(db, service.get_receipt(db, grn_id)))


@router.post("/receipts/{grn_id}/return", status_code=201)
def return_goods(
    grn_id: int, data: ReturnIn, db: DbDep, user: Allow("purchase_return.create"), request: Request
) -> ReturnOut:
    return ReturnOut(
        **service.return_detail(db, service.purchase_return(db, user, grn_id, data, request))
    )


@router.get("/returns")
def list_returns(
    db: DbDep,
    params: PageParamsDep,
    _: Allow("purchase_return.view"),
    supplier_id: int | None = None,
    date_from: DateFrom = None,
    date_to: DateTo = None,
) -> Page[ReturnOut]:
    return Page[ReturnOut](**service.list_returns(db, params, supplier_id, date_from, date_to))


@router.get("/returns/{ret_id}")
def get_return(ret_id: int, db: DbDep, _: Allow("purchase_return.view")) -> ReturnOut:
    return ReturnOut(**service.return_detail(db, service.get_return(db, ret_id)))
