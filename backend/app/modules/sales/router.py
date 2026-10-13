from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request

from app.core.deps import Allow, DbDep
from app.core.errors import AppError
from app.core.pagination import Page, PageParamsDep
from app.modules.sales import service
from app.modules.sales.schemas import (
    ConvertIn,
    DeliverIn,
    DeliveryOut,
    InvoiceDetailOut,
    InvoiceOut,
    InvoiceStatus,
    ProducedIn,
    QuotationDetailOut,
    QuotationIn,
    QuotationOut,
    QuotationStatus,
    ReserveIn,
    ReserveOut,
    SalesReturnIn,
    SalesReturnOut,
    SoDetailOut,
    SoIn,
    SoOut,
    SoStatus,
)

router = APIRouter(prefix="/sales", tags=["sales"])

DateFrom = Annotated[date | None, Query(alias="from")]
DateTo = Annotated[date | None, Query(alias="to")]


def _qt(db: DbDep, qt_id: int) -> QuotationDetailOut:
    return QuotationDetailOut(**service.quotation_detail(db, service.get_quotation(db, qt_id)))


def _so(db: DbDep, so_id: int) -> SoDetailOut:
    return SoDetailOut(**service.so_detail(db, service.get_so(db, so_id)))


def _inv(db: DbDep, invoice_id: int) -> InvoiceDetailOut:
    return InvoiceDetailOut(**service.invoice_detail(db, service.get_invoice(db, invoice_id)))


# --- quotations --------------------------------------------------------------------------


@router.get("/quotations")
def list_quotations(
    db: DbDep,
    params: PageParamsDep,
    _: Allow("quotation.view"),
    customer_id: int | None = None,
    status: QuotationStatus | None = None,
    date_from: DateFrom = None,
    date_to: DateTo = None,
) -> Page[QuotationOut]:
    return Page[QuotationOut](
        **service.list_quotations(db, params, customer_id, status, date_from, date_to)
    )


@router.post("/quotations", status_code=201)
def create_quotation(
    data: QuotationIn, db: DbDep, user: Allow("quotation.create"), request: Request
) -> QuotationDetailOut:
    return _qt(db, service.create_quotation(db, user, data, request).id)


@router.get("/quotations/{qt_id}")
def get_quotation(qt_id: int, db: DbDep, _: Allow("quotation.view")) -> QuotationDetailOut:
    return _qt(db, qt_id)


@router.put("/quotations/{qt_id}")
def update_quotation(
    qt_id: int, data: QuotationIn, db: DbDep, user: Allow("quotation.edit"), request: Request
) -> QuotationDetailOut:
    return _qt(db, service.update_quotation(db, user, qt_id, data, request).id)


@router.post("/quotations/{qt_id}/convert", status_code=201)
def convert_quotation(
    qt_id: int, data: ConvertIn, db: DbDep, user: Allow("sales_order.create"), request: Request
) -> SoDetailOut:
    so = service.convert_to_sales_order(db, user, qt_id, data.warehouse_id, request)
    return _so(db, so.id)


@router.post("/quotations/{qt_id}/{action}")
def quotation_status(
    qt_id: int,
    action: Literal["send", "accept", "reject"],
    db: DbDep,
    user: Allow("quotation.edit"),
    request: Request,
) -> QuotationDetailOut:
    return _qt(db, service.set_quotation_status(db, user, qt_id, action, request).id)


# --- sales orders ------------------------------------------------------------------------


@router.get("/orders")
def list_orders(
    db: DbDep,
    params: PageParamsDep,
    _: Allow("sales_order.view"),
    customer_id: int | None = None,
    status: SoStatus | None = None,
    date_from: DateFrom = None,
    date_to: DateTo = None,
) -> Page[SoOut]:
    return Page[SoOut](**service.list_sos(db, params, customer_id, status, date_from, date_to))


@router.post("/orders", status_code=201)
def create_order(
    data: SoIn, db: DbDep, user: Allow("sales_order.create"), request: Request
) -> SoDetailOut:
    return _so(db, service.create_so(db, user, data, request).id)


@router.get("/orders/{so_id}")
def get_order(so_id: int, db: DbDep, _: Allow("sales_order.view")) -> SoDetailOut:
    return _so(db, so_id)


@router.put("/orders/{so_id}")
def update_order(
    so_id: int, data: SoIn, db: DbDep, user: Allow("sales_order.edit"), request: Request
) -> SoDetailOut:
    return _so(db, service.update_so(db, user, so_id, data, request).id)


@router.post("/orders/{so_id}/confirm")
def confirm_order(
    so_id: int, db: DbDep, user: Allow("sales_order.edit"), request: Request
) -> SoDetailOut:
    return _so(db, service.confirm_so(db, user, so_id, request).id)


@router.put("/orders/{so_id}/items/{item_id}/produced")
def set_produced(
    so_id: int,
    item_id: int,
    data: ProducedIn,
    db: DbDep,
    user: Allow("sales_order.edit"),
    request: Request,
) -> SoDetailOut:
    service.set_produced(db, user, so_id, item_id, data.qty_produced, request)
    return _so(db, so_id)


@router.post("/orders/{so_id}/cancel")
def cancel_order(
    so_id: int, db: DbDep, user: Allow("sales_order.delete"), request: Request
) -> SoDetailOut:
    return _so(db, service.cancel_so(db, user, so_id, request).id)


@router.post("/orders/{so_id}/reserve")
def reserve(
    so_id: int, data: ReserveIn, db: DbDep, user: Allow("reservation.manage"), request: Request
) -> ReserveOut:
    so, lines = service.reserve_order(db, user, so_id, data.warehouse_id, request)
    return ReserveOut(order=_so(db, so.id), lines=lines)


@router.post("/orders/{so_id}/release")
def release(
    so_id: int, db: DbDep, user: Allow("reservation.manage"), request: Request
) -> SoDetailOut:
    return _so(db, service.release_reservation(db, user, so_id, request).id)


@router.post("/orders/{so_id}/deliver", status_code=201)
def deliver(
    so_id: int, data: DeliverIn, db: DbDep, user: Allow("delivery.create"), request: Request
) -> DeliveryOut:
    if data.create_invoice and "invoice.create" not in user.permission_codes:
        raise AppError(403, "PERMISSION_DENIED", "You do not have permission: invoice.create")
    dlv = service.deliver(db, user, so_id, data, request)
    return DeliveryOut(**service.delivery_detail(db, dlv))


# --- deliveries --------------------------------------------------------------------------


@router.get("/deliveries")
def list_deliveries(
    db: DbDep,
    params: PageParamsDep,
    _: Allow("delivery.view"),
    customer_id: int | None = None,
    sales_order_id: int | None = None,
    date_from: DateFrom = None,
    date_to: DateTo = None,
) -> Page[DeliveryOut]:
    return Page[DeliveryOut](
        **service.list_deliveries(db, params, customer_id, sales_order_id, date_from, date_to)
    )


@router.get("/deliveries/{dlv_id}")
def get_delivery(dlv_id: int, db: DbDep, _: Allow("delivery.view")) -> DeliveryOut:
    return DeliveryOut(**service.delivery_detail(db, service.get_delivery(db, dlv_id)))


@router.post("/deliveries/{dlv_id}/invoice", status_code=201)
def invoice_delivery(
    dlv_id: int, db: DbDep, user: Allow("invoice.create"), request: Request
) -> InvoiceDetailOut:
    return _inv(db, service.invoice_delivery(db, user, dlv_id, request).id)


# --- invoices & returns ------------------------------------------------------------------


@router.get("/invoices")
def list_invoices(
    db: DbDep,
    params: PageParamsDep,
    _: Allow("invoice.view"),
    customer_id: int | None = None,
    status: InvoiceStatus | None = None,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    sales_order_id: int | None = None,
) -> Page[InvoiceOut]:
    return Page[InvoiceOut](
        **service.list_invoices(db, params, customer_id, status, date_from, date_to, sales_order_id)
    )


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int, db: DbDep, _: Allow("invoice.view")) -> InvoiceDetailOut:
    return _inv(db, invoice_id)


@router.post("/invoices/{invoice_id}/return", status_code=201)
def return_goods(
    invoice_id: int,
    data: SalesReturnIn,
    db: DbDep,
    user: Allow("sales_return.create"),
    request: Request,
) -> SalesReturnOut:
    ret = service.sales_return(db, user, invoice_id, data, request)
    return SalesReturnOut(**service.return_detail(db, ret))


@router.get("/returns")
def list_returns(
    db: DbDep,
    params: PageParamsDep,
    _: Allow("sales_return.view"),
    customer_id: int | None = None,
    invoice_id: int | None = None,
    date_from: DateFrom = None,
    date_to: DateTo = None,
) -> Page[SalesReturnOut]:
    return Page[SalesReturnOut](
        **service.list_returns(db, params, customer_id, invoice_id, date_from, date_to)
    )


@router.get("/returns/{ret_id}")
def get_return(ret_id: int, db: DbDep, _: Allow("sales_return.view")) -> SalesReturnOut:
    return SalesReturnOut(**service.return_detail(db, service.get_return(db, ret_id)))
