"""Sales: quotations, sales orders (reservation, delivery), invoices and sales returns.

Every posting is one transaction (`atomic`): the document, the stock movements (inventory
engine), the customer ledger entry and any refund (money engine) all succeed or none do.
Stock, ledger and money calls go through the module objects (`inventory.stock_out`,
`parties.post_party_entry`, `money.money_out`) so each engine stays the single
implementation (and tests can make them fail).

Discount: the sales order discount is shared across its invoices in proportion to value;
the invoice completing the order takes the exact remainder. Returns get the invoice's
discount share the same way.
"""

from collections.abc import Iterable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.dates import today
from app.core.db import atomic, utcnow
from app.core.errors import AppError
from app.core.numbering import next_document_number
from app.core.pagination import PageParams
from app.modules.admin.service import get_company_settings
from app.modules.auth.models import User
from app.modules.inventory import service as inventory
from app.modules.inventory.models import SALE_OUT, SALE_RETURN_IN
from app.modules.master.models import Product, Unit, Warehouse
from app.modules.money import service as money
from app.modules.money.models import REFUND, CustomerCollection, MoneyAccount
from app.modules.parties import service as parties
from app.modules.parties.models import CUSTOMER, Customer
from app.modules.sales import payments
from app.modules.sales.models import (
    ACCEPTED,
    CANCELLED,
    CONFIRMED,
    CONVERTED,
    DELIVERED,
    DRAFT,
    PARTIALLY_DELIVERED,
    REJECTED,
    SENT,
    UNPAID,
    Delivery,
    DeliveryItem,
    Invoice,
    InvoiceItem,
    Quotation,
    QuotationItem,
    SalesOrder,
    SalesOrderItem,
    SalesReturn,
    SalesReturnItem,
)
from app.modules.sales.schemas import DeliverIn, QuotationIn, SalesReturnIn, SoIn

Q2 = Decimal("0.01")
ZERO = Decimal("0")
DELIVERY = "DELIVERY"
INVOICE = "INVOICE"
SALES_RETURN = "SALES_RETURN"
SALES_REFUND = "SALES_REFUND"


def _money(value: Decimal) -> Decimal:
    return value.quantize(Q2, ROUND_HALF_UP)


def _fmt(qty: Decimal) -> str:
    return f"{qty.normalize():f}"


# =========================================================================================
# Validation / locking helpers
# =========================================================================================


def _active_customer(db: Session, customer_id: int) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise AppError(400, "INVALID_CUSTOMER", "Customer does not exist")
    if not customer.is_active:
        raise AppError(400, "INACTIVE_CUSTOMER", f"Customer {customer.name} is inactive")
    return customer


def _active_warehouse(db: Session, warehouse_id: int) -> Warehouse:
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise AppError(400, "INVALID_WAREHOUSE", "Warehouse does not exist")
    if not warehouse.is_active:
        raise AppError(400, "INACTIVE_WAREHOUSE", f"Warehouse {warehouse.name} is inactive")
    return warehouse


def _default_warehouse(db: Session) -> Warehouse:
    warehouse = db.scalar(
        select(Warehouse)
        .where(Warehouse.is_active.is_(True))
        .order_by(Warehouse.is_default.desc(), Warehouse.id)
        .limit(1)
    )
    if warehouse is None:
        raise AppError(400, "INVALID_WAREHOUSE", "No active warehouse exists")
    return warehouse


def _active_products(db: Session, product_ids: list[int]) -> None:
    if len(product_ids) != len(set(product_ids)):
        raise AppError(400, "DUPLICATE_LINE", "Each product may appear only once per document")
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(product_ids)))}
    for pid in product_ids:
        product = products.get(pid)
        if product is None:
            raise AppError(400, "INVALID_PRODUCT", f"Product {pid} does not exist")
        if not product.is_active:
            raise AppError(400, "INACTIVE_PRODUCT", f"Product {product.code} is inactive")


def _lock(db: Session, model: Any, doc_id: int, code: str, label: str) -> Any:
    doc = db.scalar(
        select(model)
        .where(model.id == doc_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if doc is None:
        raise AppError(404, code, f"{label} not found")
    return doc


def _lock_quotation(db: Session, qt_id: int) -> Quotation:
    return _lock(db, Quotation, qt_id, "QUOTATION_NOT_FOUND", "Quotation")


def _lock_so(db: Session, so_id: int) -> SalesOrder:
    return _lock(db, SalesOrder, so_id, "SO_NOT_FOUND", "Sales order")


def _require_status(number: str, status: str, allowed: Iterable[str], action: str) -> None:
    if status not in allowed:
        nice = status.replace("_", " ")
        raise AppError(400, "INVALID_STATUS", f"Cannot {action} {number}: it is {nice}")


def _totals(db: Session, data: QuotationIn | SoIn) -> tuple[list[tuple[Any, Decimal]], Decimal]:
    """Validate lines and return [(line_in, line_total)], subtotal."""
    _active_customer(db, data.customer_id)
    _active_products(db, [i.product_id for i in data.items])
    lines = [(i, _money(i.qty * i.unit_price)) for i in data.items]
    subtotal = sum((t for _, t in lines), ZERO)
    if data.discount > subtotal:
        raise AppError(400, "INVALID_DISCOUNT", "Discount cannot be more than the subtotal")
    return lines, subtotal


def _audit(
    db: Session,
    user: User,
    action: str,
    entity: str,
    entity_id: int,
    summary: str,
    request: Request | None,
    old: Any = None,
    new: Any = None,
) -> None:
    log_audit(db, user, action, entity, entity_id, summary, old=old, new=new, request=request)


# =========================================================================================
# Quotations
# =========================================================================================


def _apply_quotation(db: Session, qt: Quotation, data: QuotationIn) -> None:
    lines, subtotal = _totals(db, data)
    qt.customer_id = data.customer_id
    qt.quote_date = data.quote_date or today()
    qt.valid_until = data.valid_until
    qt.notes = data.notes
    qt.subtotal, qt.discount, qt.total = subtotal, data.discount, subtotal - data.discount
    qt.items = [
        QuotationItem(product_id=i.product_id, qty=i.qty, unit_price=i.unit_price, line_total=t)
        for i, t in lines
    ]


def create_quotation(
    db: Session, user: User, data: QuotationIn, request: Request | None = None
) -> Quotation:
    with atomic(db):
        qt = Quotation(qt_number=next_document_number(db, "QT"), status=DRAFT, created_by=user.id)
        _apply_quotation(db, qt, data)
        db.add(qt)
        db.flush()
        _audit(
            db,
            user,
            "create",
            "quotation",
            qt.id,
            f"Created {qt.qt_number}",
            request,
            new=data.model_dump(),
        )
    return qt


def update_quotation(
    db: Session, user: User, qt_id: int, data: QuotationIn, request: Request | None = None
) -> Quotation:
    with atomic(db):
        qt = _lock_quotation(db, qt_id)
        _require_status(qt.qt_number, qt.status, (DRAFT,), "edit")
        old = {"customer_id": qt.customer_id, "total": qt.total, "lines": len(qt.items)}
        _apply_quotation(db, qt, data)
        db.flush()
        _audit(
            db,
            user,
            "update",
            "quotation",
            qt.id,
            f"Updated {qt.qt_number}",
            request,
            old=old,
            new=data.model_dump(),
        )
    return qt


_QT_TRANSITIONS = {
    "send": ((DRAFT,), SENT, "Sent"),
    "accept": ((SENT,), ACCEPTED, "Accepted"),
    "reject": ((SENT,), REJECTED, "Rejected"),
}


def set_quotation_status(
    db: Session, user: User, qt_id: int, action: str, request: Request | None = None
) -> Quotation:
    allowed, new_status, verb = _QT_TRANSITIONS[action]
    with atomic(db):
        qt = _lock_quotation(db, qt_id)
        _require_status(qt.qt_number, qt.status, allowed, action)
        old = qt.status
        qt.status = new_status
        _audit(
            db,
            user,
            "update",
            "quotation",
            qt.id,
            f"{verb} {qt.qt_number}",
            request,
            old={"status": old},
            new={"status": new_status},
        )
    return qt


def convert_to_sales_order(
    db: Session,
    user: User,
    qt_id: int,
    warehouse_id: int | None = None,
    request: Request | None = None,
) -> SalesOrder:
    """Copy the quotation into a new draft sales order and mark it converted."""
    with atomic(db):
        qt = _lock_quotation(db, qt_id)
        _require_status(qt.qt_number, qt.status, (DRAFT, SENT, ACCEPTED), "convert")
        _active_customer(db, qt.customer_id)
        _active_products(db, [i.product_id for i in qt.items])
        warehouse = _active_warehouse(db, warehouse_id) if warehouse_id else _default_warehouse(db)
        so = SalesOrder(
            so_number=next_document_number(db, "SO"),
            customer_id=qt.customer_id,
            quotation_id=qt.id,
            warehouse_id=warehouse.id,
            order_date=today(),
            status=DRAFT,
            subtotal=qt.subtotal,
            discount=qt.discount,
            total=qt.total,
            notes=qt.notes,
            created_by=user.id,
            items=[
                SalesOrderItem(
                    product_id=i.product_id,
                    qty_ordered=i.qty,
                    unit_price=i.unit_price,
                    line_total=i.line_total,
                    qty_reserved=ZERO,
                    qty_produced=ZERO,
                    qty_delivered=ZERO,
                )
                for i in qt.items
            ],
        )
        db.add(so)
        db.flush()
        old = qt.status
        qt.status = CONVERTED
        qt.converted_order_id = so.id
        _audit(
            db,
            user,
            "create",
            "sales_order",
            so.id,
            f"Created {so.so_number} from {qt.qt_number}",
            request,
            new={"quotation_id": qt.id},
        )
        _audit(
            db,
            user,
            "update",
            "quotation",
            qt.id,
            f"Converted {qt.qt_number} to {so.so_number}",
            request,
            old={"status": old},
            new={"status": CONVERTED, "sales_order_id": so.id},
        )
    return so


# =========================================================================================
# Sales orders
# =========================================================================================


def _apply_so(db: Session, so: SalesOrder, data: SoIn) -> None:
    lines, subtotal = _totals(db, data)
    _active_warehouse(db, data.warehouse_id)
    so.customer_id = data.customer_id
    so.warehouse_id = data.warehouse_id
    so.order_date = data.order_date or today()
    so.delivery_date = data.delivery_date
    so.notes = data.notes
    so.subtotal, so.discount, so.total = subtotal, data.discount, subtotal - data.discount
    so.items = [
        SalesOrderItem(
            product_id=i.product_id,
            qty_ordered=i.qty,
            unit_price=i.unit_price,
            line_total=t,
            qty_reserved=ZERO,
            qty_produced=ZERO,
            qty_delivered=ZERO,
        )
        for i, t in lines
    ]


def create_so(db: Session, user: User, data: SoIn, request: Request | None = None) -> SalesOrder:
    with atomic(db):
        so = SalesOrder(so_number=next_document_number(db, "SO"), status=DRAFT, created_by=user.id)
        _apply_so(db, so, data)
        db.add(so)
        db.flush()
        _audit(
            db,
            user,
            "create",
            "sales_order",
            so.id,
            f"Created {so.so_number}",
            request,
            new=data.model_dump(),
        )
    return so


def update_so(
    db: Session, user: User, so_id: int, data: SoIn, request: Request | None = None
) -> SalesOrder:
    with atomic(db):
        so = _lock_so(db, so_id)
        _require_status(so.so_number, so.status, (DRAFT,), "edit")
        old = {
            "customer_id": so.customer_id,
            "warehouse_id": so.warehouse_id,
            "total": so.total,
            "lines": len(so.items),
        }
        _apply_so(db, so, data)
        db.flush()
        _audit(
            db,
            user,
            "update",
            "sales_order",
            so.id,
            f"Updated {so.so_number}",
            request,
            old=old,
            new=data.model_dump(),
        )
    return so


def confirm_so(db: Session, user: User, so_id: int, request: Request | None = None) -> SalesOrder:
    with atomic(db):
        so = _lock_so(db, so_id)
        _require_status(so.so_number, so.status, (DRAFT,), "confirm")
        so.status = CONFIRMED
        so.confirmed_by = user.id
        so.confirmed_at = utcnow()
        _audit(
            db,
            user,
            "approve",
            "sales_order",
            so.id,
            f"Confirmed {so.so_number}",
            request,
            old={"status": DRAFT},
            new={"status": CONFIRMED},
        )
    return so


def set_produced(
    db: Session,
    user: User,
    so_id: int,
    so_item_id: int,
    qty: Decimal,
    request: Request | None = None,
) -> SalesOrder:
    """Manual 'produced' figure (no production module): 0..ordered."""
    with atomic(db):
        so = _lock_so(db, so_id)
        _require_status(so.so_number, so.status, (DRAFT, CONFIRMED, PARTIALLY_DELIVERED), "update")
        line = next((i for i in so.items if i.id == so_item_id), None)
        if line is None:
            raise AppError(400, "INVALID_LINE", f"Line {so_item_id} is not on {so.so_number}")
        if qty > line.qty_ordered:
            raise AppError(
                400,
                "INVALID_QTY",
                f"Produced cannot exceed the ordered quantity {_fmt(line.qty_ordered)}",
            )
        old = line.qty_produced
        line.qty_produced = qty
        _audit(
            db,
            user,
            "update",
            "sales_order",
            so.id,
            f"Set produced qty on {so.so_number} line {line.id}",
            request,
            old={"qty_produced": old},
            new={"qty_produced": qty},
        )
    return so


def _release_all(db: Session, so: SalesOrder) -> Decimal:
    released = ZERO
    for line in sorted(so.items, key=lambda i: i.product_id):
        if line.qty_reserved > 0:
            inventory.release(db, line.product_id, so.warehouse_id, line.qty_reserved)
            released += line.qty_reserved
            line.qty_reserved = ZERO
    return released


def cancel_so(db: Session, user: User, so_id: int, request: Request | None = None) -> SalesOrder:
    with atomic(db):
        so = _lock_so(db, so_id)
        if any(i.qty_delivered > 0 for i in so.items):
            raise AppError(
                400,
                "CANNOT_CANCEL",
                f"{so.so_number} has deliveries and cannot be cancelled",
            )
        _require_status(so.so_number, so.status, (DRAFT, CONFIRMED), "cancel")
        old = so.status
        released = _release_all(db, so)
        so.status = CANCELLED
        _audit(
            db,
            user,
            "cancel",
            "sales_order",
            so.id,
            f"Cancelled {so.so_number}",
            request,
            old={"status": old},
            new={"status": CANCELLED, "released": released},
        )
    return so


# --- reservation -------------------------------------------------------------------------


def reserve_order(
    db: Session,
    user: User,
    so_id: int,
    warehouse_id: int | None = None,
    request: Request | None = None,
) -> tuple[SalesOrder, list[dict[str, Any]]]:
    """Reserve min(available, remaining - reserved) per line. Partial results are fine;
    the returned lines say what was reserved and what is still short."""
    with atomic(db):
        so = _lock_so(db, so_id)
        _require_status(so.so_number, so.status, (CONFIRMED, PARTIALLY_DELIVERED), "reserve")
        if warehouse_id is not None and warehouse_id != so.warehouse_id:
            if any(i.qty_reserved > 0 or i.qty_delivered > 0 for i in so.items):
                raise AppError(
                    400,
                    "WAREHOUSE_LOCKED",
                    f"{so.so_number} already has reserved or delivered stock in its "
                    "warehouse; release it first to use another warehouse",
                )
            _active_warehouse(db, warehouse_id)
            so.warehouse_id = warehouse_id
        products = _by_id(db, Product, [i.product_id for i in so.items])
        result = []
        for line in sorted(so.items, key=lambda i: i.product_id):
            wanted = line.qty_ordered - line.qty_delivered - line.qty_reserved
            got = ZERO
            if wanted > 0:
                got = inventory.reserve_up_to(db, line.product_id, so.warehouse_id, wanted)
                line.qty_reserved += got
            product = products[line.product_id]
            result.append(
                {
                    "so_item_id": line.id,
                    "product_code": product.code,
                    "product_name": product.name,
                    "wanted": max(wanted, ZERO),
                    "reserved_now": got,
                    "reserved_total": line.qty_reserved,
                    "short": max(wanted - got, ZERO),
                }
            )
        result.sort(key=lambda r: r["so_item_id"])
        total = sum((r["reserved_now"] for r in result), ZERO)
        _audit(
            db,
            user,
            "update",
            "sales_order",
            so.id,
            f"Reserved stock for {so.so_number}: {_fmt(total)} units",
            request,
            new={"warehouse_id": so.warehouse_id, "lines": result},
        )
    return so, result


def release_reservation(
    db: Session, user: User, so_id: int, request: Request | None = None
) -> SalesOrder:
    with atomic(db):
        so = _lock_so(db, so_id)
        _require_status(so.so_number, so.status, (CONFIRMED, PARTIALLY_DELIVERED), "release")
        released = _release_all(db, so)
        if released == 0:
            raise AppError(400, "NOTHING_RESERVED", f"{so.so_number} has no reserved stock")
        _audit(
            db,
            user,
            "update",
            "sales_order",
            so.id,
            f"Released reservation of {so.so_number}: {_fmt(released)} units",
            request,
            new={"released": released},
        )
    return so


# --- delivery ----------------------------------------------------------------------------


def deliver(
    db: Session, user: User, so_id: int, data: DeliverIn, request: Request | None = None
) -> Delivery:
    """Stock OUT (reservation first), COGS per line, SO progress and (by default) the
    invoice + customer ledger debit - one transaction."""
    with atomic(db):
        so = _lock_so(db, so_id)
        _require_status(so.so_number, so.status, (CONFIRMED, PARTIALLY_DELIVERED), "deliver")
        by_id = {i.id: i for i in so.items}
        ids = [i.so_item_id for i in data.items]
        if len(ids) != len(set(ids)):
            raise AppError(400, "DUPLICATE_LINE", "Each order line may appear only once")
        when = data.delivery_date or today()
        dlv = Delivery(
            dlv_number=next_document_number(db, "DLV"),
            sales_order_id=so.id,
            customer_id=so.customer_id,
            warehouse_id=so.warehouse_id,
            delivery_date=when,
            notes=data.notes,
            created_by=user.id,
        )
        db.add(dlv)
        db.flush()
        lines = []
        for item in data.items:
            line = by_id.get(item.so_item_id)
            if line is None:
                raise AppError(
                    400, "INVALID_LINE", f"Line {item.so_item_id} is not on {so.so_number}"
                )
            remaining = line.qty_ordered - line.qty_delivered
            if item.qty > remaining:
                raise AppError(
                    400,
                    "OVER_DELIVERY",
                    f"Cannot deliver {_fmt(item.qty)} of line {line.id}: only "
                    f"{_fmt(remaining)} remaining on {so.so_number}",
                )
            lines.append((line, item.qty))
        # Lock stock rows in product order (deadlock-free with concurrent deliveries).
        for line, qty in sorted(lines, key=lambda x: x[0].product_id):
            from_reservation = min(qty, line.qty_reserved)
            cogs = inventory.stock_out(
                db,
                line.product_id,
                so.warehouse_id,
                qty,
                SALE_OUT,
                DELIVERY,
                dlv.id,
                when,
                user,
                reserved_qty=from_reservation,
                note=f"{dlv.dlv_number} / {so.so_number}",
            )
            line.qty_reserved -= from_reservation
            line.qty_delivered += qty
            dlv.items.append(
                DeliveryItem(
                    so_item_id=line.id,
                    product_id=line.product_id,
                    qty=qty,
                    unit_cost_cogs=cogs,
                    unit_price=line.unit_price,
                )
            )
        complete = all(i.qty_delivered >= i.qty_ordered for i in so.items)
        old_status = so.status
        so.status = DELIVERED if complete else PARTIALLY_DELIVERED
        db.flush()
        _audit(
            db,
            user,
            "post",
            "delivery",
            dlv.id,
            f"Delivered {dlv.dlv_number} for {so.so_number}",
            request,
            old={"so_status": old_status},
            new={"so_status": so.status, "lines": len(dlv.items)},
        )
        if data.create_invoice:
            _invoice_delivery(db, user, so, dlv, when, request)
    return dlv


def _invoice_delivery(
    db: Session,
    user: User,
    so: SalesOrder,
    dlv: Delivery,
    invoice_date: date,
    request: Request | None,
) -> Invoice:
    """Invoice every line of `dlv` and post the customer ledger debit (caller's
    transaction; `so` must be locked)."""
    invoice = Invoice(
        inv_number=next_document_number(db, "INV"),
        customer_id=so.customer_id,
        sales_order_id=so.id,
        delivery_id=dlv.id,
        invoice_date=invoice_date,
        subtotal=ZERO,
        discount=ZERO,
        total=ZERO,
        paid_amount=ZERO,
        returned_amount=ZERO,
        refunded_amount=ZERO,
        status=UNPAID,
        cogs_total=ZERO,
        created_by=user.id,
    )
    db.add(invoice)
    db.flush()
    for d in dlv.items:
        invoice.items.append(
            InvoiceItem(
                delivery_item_id=d.id,
                product_id=d.product_id,
                qty=d.qty,
                unit_price=d.unit_price,
                unit_cost=d.unit_cost_cogs,
                line_total=_money(d.qty * d.unit_price),
                qty_returned=ZERO,
            )
        )
    subtotal = sum((i.line_total for i in invoice.items), ZERO)
    cogs_total = sum((_money(i.qty * i.unit_cost) for i in invoice.items), ZERO)
    discount = ZERO
    if so.discount > 0 and so.subtotal > 0:
        given = db.scalar(
            select(func.coalesce(func.sum(Invoice.discount), 0)).where(
                Invoice.sales_order_id == so.id, Invoice.id != invoice.id
            )
        )
        uninvoiced = db.scalar(
            select(func.count(Delivery.id)).where(
                Delivery.sales_order_id == so.id,
                Delivery.invoice_id.is_(None),
                Delivery.id != dlv.id,
            )
        )
        left = so.discount - Decimal(given or 0)
        # The invoice that completes the order takes the exact remainder.
        complete = so.status == DELIVERED and not uninvoiced
        share = left if complete else _money(so.discount * subtotal / so.subtotal)
        discount = max(ZERO, min(share, left, subtotal))
    invoice.subtotal, invoice.discount, invoice.total = subtotal, discount, subtotal - discount
    invoice.cogs_total = cogs_total
    payments.refresh_status(invoice)
    dlv.invoice_id = invoice.id
    if invoice.total > 0:
        parties.post_party_entry(
            db,
            CUSTOMER,
            so.customer_id,
            invoice_date,
            invoice.total,
            ZERO,
            INVOICE,
            invoice.id,
            f"{invoice.inv_number} ({dlv.dlv_number})",
            user,
        )
    db.flush()
    _audit(
        db,
        user,
        "post",
        "invoice",
        invoice.id,
        f"Invoiced {invoice.inv_number} for {dlv.dlv_number}: {invoice.total:.2f}",
        request,
        new={
            "delivery_id": dlv.id,
            "subtotal": invoice.subtotal,
            "discount": invoice.discount,
            "total": invoice.total,
            "cogs_total": invoice.cogs_total,
        },
    )
    return invoice


def invoice_delivery(
    db: Session, user: User, dlv_id: int, request: Request | None = None
) -> Invoice:
    """Invoice a delivery that was posted without one."""
    with atomic(db):
        dlv = get_delivery(db, dlv_id)
        so = _lock_so(db, dlv.sales_order_id)
        dlv = _lock(db, Delivery, dlv_id, "DELIVERY_NOT_FOUND", "Delivery")
        if dlv.invoice_id is not None:
            raise AppError(400, "ALREADY_INVOICED", f"{dlv.dlv_number} is already invoiced")
        invoice = _invoice_delivery(db, user, so, dlv, today(), request)
    return invoice


# =========================================================================================
# Sales returns
# =========================================================================================


def sales_return(
    db: Session, user: User, invoice_id: int, data: SalesReturnIn, request: Request | None = None
) -> SalesReturn:
    """Stock IN at the original COGS, customer credit, optional refund (money OUT +
    customer debit) - one transaction."""
    with atomic(db):
        invoice = payments.lock_invoice(db, invoice_id)
        dlv = db.get(Delivery, invoice.delivery_id)
        assert dlv is not None
        by_id = {i.id: i for i in invoice.items}
        ids = [i.invoice_item_id for i in data.items]
        if len(ids) != len(set(ids)):
            raise AppError(400, "DUPLICATE_LINE", "Each invoice line may appear only once")
        refund = data.refund_amount
        if refund > 0:
            if data.refund_account_id is None:
                raise AppError(
                    400, "ACCOUNT_REQUIRED", "Choose the account the refund is paid from"
                )
            money._active_account(db, data.refund_account_id)
        when = data.return_date or today()
        ret = SalesReturn(
            srn_number=next_document_number(db, "SRN"),
            invoice_id=invoice.id,
            customer_id=invoice.customer_id,
            warehouse_id=dlv.warehouse_id,
            return_date=when,
            subtotal=ZERO,
            discount=ZERO,
            total=ZERO,
            refund_amount=ZERO,
            refund_account_id=data.refund_account_id if refund > 0 else None,
            notes=data.notes,
            created_by=user.id,
        )
        db.add(ret)
        db.flush()
        lines = []
        for item in data.items:
            line = by_id.get(item.invoice_item_id)
            if line is None:
                raise AppError(
                    400,
                    "INVALID_LINE",
                    f"Line {item.invoice_item_id} is not on {invoice.inv_number}",
                )
            returnable = line.qty - line.qty_returned
            if item.qty > returnable:
                raise AppError(
                    400,
                    "OVER_RETURN",
                    f"Cannot return {_fmt(item.qty)} of line {line.id}: only "
                    f"{_fmt(returnable)} returnable on {invoice.inv_number}",
                )
            lines.append((line, item.qty))
        for line, qty in sorted(lines, key=lambda x: x[0].product_id):
            # Back into stock at the COGS recorded on the delivery line.
            inventory.stock_in(
                db,
                line.product_id,
                dlv.warehouse_id,
                qty,
                line.unit_cost,
                SALE_RETURN_IN,
                SALES_RETURN,
                ret.id,
                when,
                user,
                f"{ret.srn_number} / {invoice.inv_number}",
            )
            line.qty_returned += qty
            ret.items.append(
                SalesReturnItem(
                    invoice_item_id=line.id,
                    product_id=line.product_id,
                    qty=qty,
                    unit_price=line.unit_price,
                    unit_cost=line.unit_cost,
                    line_total=_money(qty * line.unit_price),
                )
            )
        subtotal = sum((i.line_total for i in ret.items), ZERO)
        discount = ZERO
        if invoice.discount > 0 and invoice.subtotal > 0:
            given = db.scalar(
                select(func.coalesce(func.sum(SalesReturn.discount), 0)).where(
                    SalesReturn.invoice_id == invoice.id, SalesReturn.id != ret.id
                )
            )
            left = invoice.discount - Decimal(given or 0)
            complete = all(i.qty_returned >= i.qty for i in invoice.items)
            share = left if complete else _money(subtotal * invoice.discount / invoice.subtotal)
            discount = max(ZERO, min(share, left, subtotal))
        total = subtotal - discount
        if refund > total:
            raise AppError(
                400,
                "INVALID_REFUND",
                f"Refund {refund:,.2f} cannot be more than the return total {total:,.2f}",
            )
        ret.subtotal, ret.discount, ret.total = subtotal, discount, total
        ret.refund_amount = refund
        if total > 0:
            parties.post_party_entry(
                db,
                CUSTOMER,
                invoice.customer_id,
                when,
                ZERO,
                total,
                SALES_RETURN,
                ret.id,
                f"{ret.srn_number} (return on {invoice.inv_number})",
                user,
            )
        if refund > 0:
            assert data.refund_account_id is not None
            money.money_out(
                db,
                data.refund_account_id,
                refund,
                REFUND,
                SALES_RETURN,
                ret.id,
                when,
                user,
                f"Refund {ret.srn_number} / {invoice.inv_number}",
            )
            parties.post_party_entry(
                db,
                CUSTOMER,
                invoice.customer_id,
                when,
                refund,
                ZERO,
                SALES_REFUND,
                ret.id,
                f"Refund for {ret.srn_number}",
                user,
            )
        invoice.returned_amount += total
        invoice.refunded_amount += refund
        payments.refresh_status(invoice)
        db.flush()
        _audit(
            db,
            user,
            "post",
            "sales_return",
            ret.id,
            f"Sales return {ret.srn_number} on {invoice.inv_number}: {total:.2f}"
            + (f", refund {refund:.2f}" if refund else ""),
            request,
            new={
                "invoice_id": invoice.id,
                "subtotal": subtotal,
                "discount": discount,
                "total": total,
                "refund_amount": refund,
                "refund_account_id": ret.refund_account_id,
            },
        )
    return ret


# =========================================================================================
# Read side
# =========================================================================================


def _by_id(db: Session, model: Any, ids: Iterable[int | None]) -> dict[int, Any]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    return {o.id: o for o in db.scalars(select(model).where(model.id.in_(wanted)))}


class _Names:
    """Batch-loaded names for a set of documents (avoids per-row queries)."""

    def __init__(self, db: Session, docs: Iterable[Any]) -> None:
        docs = list(docs)
        self.products = _by_id(db, Product, [i.product_id for d in docs for i in d.items])
        self.units = _by_id(db, Unit, [p.unit_id for p in self.products.values()])
        self.customers = _by_id(db, Customer, [d.customer_id for d in docs])
        self.warehouses = _by_id(db, Warehouse, [getattr(d, "warehouse_id", None) for d in docs])
        self.users = _by_id(
            db,
            User,
            [u for d in docs for u in (d.created_by, getattr(d, "confirmed_by", None))],
        )

    def line(self, item: Any) -> dict[str, Any]:
        p = self.products[item.product_id]
        return {
            "id": item.id,
            "product_id": p.id,
            "product_code": p.code,
            "product_name": p.name,
            "unit_code": self.units[p.unit_id].short_code,
        }

    def customer(self, customer_id: int) -> dict[str, Any]:
        c = self.customers[customer_id]
        return {"customer_id": c.id, "customer_code": c.code, "customer_name": c.name}

    def user(self, user_id: int | None) -> str | None:
        return self.users[user_id].full_name if user_id in self.users else None


def _page(db: Session, stmt: Any, params: PageParams) -> tuple[int, list[Any]]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    return total, list(db.scalars(stmt.limit(params.page_size).offset(params.offset)))


def _filtered(
    stmt: Any,
    model: Any,
    date_col: Any,
    number_col: Any,
    params: PageParams,
    customer_id: int | None,
    status: str | None,
    date_from: date | None,
    date_to: date | None,
) -> Any:
    if customer_id is not None:
        stmt = stmt.where(model.customer_id == customer_id)
    if status and hasattr(model, "status"):
        stmt = stmt.where(model.status == status)
    if date_from:
        stmt = stmt.where(date_col >= date_from)
    if date_to:
        stmt = stmt.where(date_col <= date_to)
    if params.search:
        stmt = stmt.join(Customer, Customer.id == model.customer_id).where(
            or_(
                number_col.contains(params.search, autoescape=True),
                Customer.name.contains(params.search, autoescape=True),
            )
        )
    return stmt


def _page_out(items: list[Any], total: int, params: PageParams) -> dict[str, Any]:
    return {"items": items, "total": total, "page": params.page, "page_size": params.page_size}


# --- quotations --------------------------------------------------------------------------


def quotation_out(db: Session, qt: Quotation, names: _Names) -> dict[str, Any]:
    so = db.get(SalesOrder, qt.converted_order_id) if qt.converted_order_id else None
    return names.customer(qt.customer_id) | {
        "id": qt.id,
        "qt_number": qt.qt_number,
        "quote_date": qt.quote_date,
        "valid_until": qt.valid_until,
        "status": qt.status,
        "subtotal": qt.subtotal,
        "discount": qt.discount,
        "total": qt.total,
        "notes": qt.notes,
        "converted_order_id": qt.converted_order_id,
        "converted_order_number": so.so_number if so else None,
        "created_by_name": names.user(qt.created_by) or "",
        "created_at": qt.created_at,
        "items": [
            names.line(i) | {"qty": i.qty, "unit_price": i.unit_price, "line_total": i.line_total}
            for i in qt.items
        ],
    }


def get_quotation(db: Session, qt_id: int) -> Quotation:
    qt = db.get(Quotation, qt_id)
    if qt is None:
        raise AppError(404, "QUOTATION_NOT_FOUND", "Quotation not found")
    return qt


def quotation_detail(db: Session, qt: Quotation) -> dict[str, Any]:
    db.refresh(qt)
    return quotation_out(db, qt, _Names(db, [qt])) | {
        "customer_due": parties.get_balance(db, CUSTOMER, qt.customer_id)
    }


def list_quotations(
    db: Session,
    params: PageParams,
    customer_id: int | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    stmt = select(Quotation).order_by(Quotation.id.desc())
    stmt = _filtered(
        stmt,
        Quotation,
        Quotation.quote_date,
        Quotation.qt_number,
        params,
        customer_id,
        status,
        date_from,
        date_to,
    )
    total, rows = _page(db, stmt, params)
    names = _Names(db, rows)
    return _page_out([quotation_out(db, q, names) for q in rows], total, params)


# --- sales orders ------------------------------------------------------------------------


def so_out(db: Session, so: SalesOrder, names: _Names, with_available: bool = False) -> dict:
    qt = db.get(Quotation, so.quotation_id) if so.quotation_id else None
    items = []
    for i in so.items:
        row = names.line(i) | {
            "qty_ordered": i.qty_ordered,
            "unit_price": i.unit_price,
            "line_total": i.line_total,
            "qty_reserved": i.qty_reserved,
            "qty_produced": i.qty_produced,
            "qty_delivered": i.qty_delivered,
            "qty_remaining": i.qty_ordered - i.qty_delivered,
        }
        if with_available:
            balance = inventory.get_balance(db, i.product_id, so.warehouse_id)
            row["qty_available"] = balance.qty_on_hand - balance.qty_reserved if balance else ZERO
        items.append(row)
    return names.customer(so.customer_id) | {
        "id": so.id,
        "so_number": so.so_number,
        "quotation_id": so.quotation_id,
        "quotation_number": qt.qt_number if qt else None,
        "warehouse_id": so.warehouse_id,
        "warehouse_name": names.warehouses[so.warehouse_id].name,
        "order_date": so.order_date,
        "delivery_date": so.delivery_date,
        "status": so.status,
        "subtotal": so.subtotal,
        "discount": so.discount,
        "total": so.total,
        "notes": so.notes,
        "created_by_name": names.user(so.created_by) or "",
        "confirmed_by_name": names.user(so.confirmed_by),
        "confirmed_at": so.confirmed_at,
        "created_at": so.created_at,
        "items": items,
    }


def get_so(db: Session, so_id: int) -> SalesOrder:
    so = db.get(SalesOrder, so_id)
    if so is None:
        raise AppError(404, "SO_NOT_FOUND", "Sales order not found")
    return so


def so_detail(db: Session, so: SalesOrder) -> dict[str, Any]:
    db.refresh(so)
    deliveries = list(
        db.scalars(select(Delivery).where(Delivery.sales_order_id == so.id).order_by(Delivery.id))
    )
    invoices = list(
        db.scalars(select(Invoice).where(Invoice.sales_order_id == so.id).order_by(Invoice.id))
    )
    return so_out(db, so, _Names(db, [so]), with_available=True) | {
        "customer_due": parties.get_balance(db, CUSTOMER, so.customer_id),
        "deliveries": deliveries_out(db, deliveries),
        "invoices": invoices_out(db, invoices),
    }


def list_sos(
    db: Session,
    params: PageParams,
    customer_id: int | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    stmt = select(SalesOrder).order_by(SalesOrder.id.desc())
    stmt = _filtered(
        stmt,
        SalesOrder,
        SalesOrder.order_date,
        SalesOrder.so_number,
        params,
        customer_id,
        status,
        date_from,
        date_to,
    )
    total, rows = _page(db, stmt, params)
    names = _Names(db, rows)
    return _page_out([so_out(db, s, names) for s in rows], total, params)


# --- deliveries --------------------------------------------------------------------------


def deliveries_out(db: Session, deliveries: list[Delivery]) -> list[dict[str, Any]]:
    names = _Names(db, deliveries)
    sos = _by_id(db, SalesOrder, [d.sales_order_id for d in deliveries])
    invoices = _by_id(db, Invoice, [d.invoice_id for d in deliveries])
    return [
        names.customer(d.customer_id)
        | {
            "id": d.id,
            "dlv_number": d.dlv_number,
            "sales_order_id": d.sales_order_id,
            "so_number": sos[d.sales_order_id].so_number,
            "warehouse_id": d.warehouse_id,
            "warehouse_name": names.warehouses[d.warehouse_id].name,
            "delivery_date": d.delivery_date,
            "invoice_id": d.invoice_id,
            "inv_number": invoices[d.invoice_id].inv_number if d.invoice_id else None,
            "notes": d.notes,
            "created_by_name": names.user(d.created_by) or "",
            "created_at": d.created_at,
            "items": [
                names.line(i)
                | {
                    "so_item_id": i.so_item_id,
                    "qty": i.qty,
                    "unit_price": i.unit_price,
                    "unit_cost_cogs": i.unit_cost_cogs,
                }
                for i in d.items
            ],
        }
        for d in deliveries
    ]


def get_delivery(db: Session, dlv_id: int) -> Delivery:
    dlv = db.get(Delivery, dlv_id)
    if dlv is None:
        raise AppError(404, "DELIVERY_NOT_FOUND", "Delivery not found")
    return dlv


def delivery_detail(db: Session, dlv: Delivery) -> dict[str, Any]:
    db.refresh(dlv)
    return deliveries_out(db, [dlv])[0]


def list_deliveries(
    db: Session,
    params: PageParams,
    customer_id: int | None = None,
    sales_order_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    stmt = select(Delivery).order_by(Delivery.id.desc())
    if sales_order_id is not None:
        stmt = stmt.where(Delivery.sales_order_id == sales_order_id)
    stmt = _filtered(
        stmt,
        Delivery,
        Delivery.delivery_date,
        Delivery.dlv_number,
        params,
        customer_id,
        None,
        date_from,
        date_to,
    )
    total, rows = _page(db, stmt, params)
    return _page_out(deliveries_out(db, rows), total, params)


# --- invoices ----------------------------------------------------------------------------


def invoices_out(db: Session, invoices: list[Invoice]) -> list[dict[str, Any]]:
    names = _Names(db, invoices)
    sos = _by_id(db, SalesOrder, [i.sales_order_id for i in invoices])
    dlvs = _by_id(db, Delivery, [i.delivery_id for i in invoices])
    warehouses = _by_id(db, Warehouse, [d.warehouse_id for d in dlvs.values()])
    out = []
    for inv in invoices:
        dlv = dlvs[inv.delivery_id]
        out.append(
            names.customer(inv.customer_id)
            | {
                "id": inv.id,
                "inv_number": inv.inv_number,
                "sales_order_id": inv.sales_order_id,
                "so_number": sos[inv.sales_order_id].so_number,
                "delivery_id": dlv.id,
                "dlv_number": dlv.dlv_number,
                "warehouse_id": dlv.warehouse_id,
                "warehouse_name": warehouses[dlv.warehouse_id].name,
                "invoice_date": inv.invoice_date,
                "subtotal": inv.subtotal,
                "discount": inv.discount,
                "total": inv.total,
                "paid_amount": inv.paid_amount,
                "returned_amount": inv.returned_amount,
                "refunded_amount": inv.refunded_amount,
                "outstanding": max(inv.outstanding, ZERO),
                "status": inv.status,
                "cogs_total": inv.cogs_total,
                "created_by_name": names.user(inv.created_by) or "",
                "created_at": inv.created_at,
                "items": [
                    names.line(i)
                    | {
                        "delivery_item_id": i.delivery_item_id,
                        "qty": i.qty,
                        "unit_price": i.unit_price,
                        "unit_cost": i.unit_cost,
                        "line_total": i.line_total,
                        "qty_returned": i.qty_returned,
                        "qty_returnable": i.qty - i.qty_returned,
                    }
                    for i in inv.items
                ],
            }
        )
    return out


def get_invoice(db: Session, invoice_id: int) -> Invoice:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise AppError(404, "INVOICE_NOT_FOUND", "Invoice not found")
    return invoice


def invoice_detail(db: Session, invoice: Invoice) -> dict[str, Any]:
    db.refresh(invoice)
    customer = db.get(Customer, invoice.customer_id)
    assert customer is not None
    rets = list(
        db.scalars(
            select(SalesReturn).where(SalesReturn.invoice_id == invoice.id).order_by(SalesReturn.id)
        )
    )
    cols = list(
        db.scalars(
            select(CustomerCollection)
            .where(CustomerCollection.invoice_id == invoice.id)
            .order_by(CustomerCollection.id)
        )
    )
    accounts = _by_id(db, MoneyAccount, [c.account_id for c in cols])
    company = get_company_settings(db)
    return invoices_out(db, [invoice])[0] | {
        "customer_due": parties.get_balance(db, CUSTOMER, invoice.customer_id),
        "customer_mobile": customer.mobile,
        "customer_address": customer.address,
        "returns": returns_out(db, rets),
        "collections": [
            {
                "id": c.id,
                "number": c.col_number,
                "collection_date": c.collection_date,
                "amount": c.amount,
                "status": c.status,
                "account_name": accounts[c.account_id].name,
            }
            for c in cols
        ],
        "company": {
            "company_name": company.company_name,
            "address": company.address,
            "phone": company.phone,
            "email": company.email,
            "currency_symbol": company.currency_symbol,
            "invoice_footer_note": company.invoice_footer_note,
            "logo_url": company.logo_url,
        },
    }


def list_invoices(
    db: Session,
    params: PageParams,
    customer_id: int | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    sales_order_id: int | None = None,
) -> dict[str, Any]:
    stmt = select(Invoice).order_by(Invoice.id.desc())
    if sales_order_id is not None:
        stmt = stmt.where(Invoice.sales_order_id == sales_order_id)
    stmt = _filtered(
        stmt,
        Invoice,
        Invoice.invoice_date,
        Invoice.inv_number,
        params,
        customer_id,
        status,
        date_from,
        date_to,
    )
    total, rows = _page(db, stmt, params)
    return _page_out(invoices_out(db, rows), total, params)


# --- returns -----------------------------------------------------------------------------


def returns_out(db: Session, rets: list[SalesReturn]) -> list[dict[str, Any]]:
    names = _Names(db, rets)
    invoices = _by_id(db, Invoice, [r.invoice_id for r in rets])
    accounts = _by_id(db, MoneyAccount, [r.refund_account_id for r in rets])
    return [
        names.customer(r.customer_id)
        | {
            "id": r.id,
            "srn_number": r.srn_number,
            "invoice_id": r.invoice_id,
            "inv_number": invoices[r.invoice_id].inv_number,
            "warehouse_id": r.warehouse_id,
            "warehouse_name": names.warehouses[r.warehouse_id].name,
            "return_date": r.return_date,
            "subtotal": r.subtotal,
            "discount": r.discount,
            "total": r.total,
            "refund_amount": r.refund_amount,
            "refund_account_id": r.refund_account_id,
            "refund_account_name": (
                accounts[r.refund_account_id].name if r.refund_account_id else None
            ),
            "notes": r.notes,
            "created_by_name": names.user(r.created_by) or "",
            "created_at": r.created_at,
            "items": [
                names.line(i)
                | {
                    "invoice_item_id": i.invoice_item_id,
                    "qty": i.qty,
                    "unit_price": i.unit_price,
                    "unit_cost": i.unit_cost,
                    "line_total": i.line_total,
                }
                for i in r.items
            ],
        }
        for r in rets
    ]


def get_return(db: Session, ret_id: int) -> SalesReturn:
    ret = db.get(SalesReturn, ret_id)
    if ret is None:
        raise AppError(404, "RETURN_NOT_FOUND", "Sales return not found")
    return ret


def return_detail(db: Session, ret: SalesReturn) -> dict[str, Any]:
    db.refresh(ret)
    return returns_out(db, [ret])[0]


def list_returns(
    db: Session,
    params: PageParams,
    customer_id: int | None = None,
    invoice_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    stmt = select(SalesReturn).order_by(SalesReturn.id.desc())
    if invoice_id is not None:
        stmt = stmt.where(SalesReturn.invoice_id == invoice_id)
    stmt = _filtered(
        stmt,
        SalesReturn,
        SalesReturn.return_date,
        SalesReturn.srn_number,
        params,
        customer_id,
        None,
        date_from,
        date_to,
    )
    total, rows = _page(db, stmt, params)
    return _page_out(returns_out(db, rows), total, params)
