"""Purchase: orders, goods receipts (incl. direct purchase) and purchase returns.

Every posting is one transaction (`atomic`): the document, the stock movements (inventory
engine) and the supplier ledger entry all succeed or none do. Stock and ledger calls go
through the module objects (`inventory.stock_in`, `parties.post_party_entry`) so the
engine stays the single implementation.

Discount is bill-only (decided with the user): stock is valued at gross line cost; each
receipt carries its share of the PO discount, which only reduces the supplier credit.
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
from app.modules.approvals import service as approvals
from app.modules.approvals.models import PURCHASE_ORDER
from app.modules.auth.models import User
from app.modules.inventory import service as inventory
from app.modules.inventory.models import PURCHASE_IN, PURCHASE_RETURN_OUT
from app.modules.master.models import Product, Unit, Warehouse
from app.modules.parties import service as parties
from app.modules.parties.models import SUPPLIER, Supplier
from app.modules.purchase.models import (
    APPROVED,
    CANCELLED,
    DRAFT,
    PARTIALLY_RECEIVED,
    PENDING_APPROVAL,
    RECEIVED,
    REJECTED,
    GoodsReceipt,
    GoodsReceiptItem,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReturn,
    PurchaseReturnItem,
)
from app.modules.purchase.schemas import DirectPurchaseIn, PoIn, ReceiveIn, ReturnIn

Q2 = Decimal("0.01")
ZERO = Decimal("0")
GOODS_RECEIPT = "GOODS_RECEIPT"
PURCHASE_RETURN = "PURCHASE_RETURN"


def _money(value: Decimal) -> Decimal:
    return value.quantize(Q2, ROUND_HALF_UP)


# =========================================================================================
# Validation / locking helpers
# =========================================================================================


def _active_supplier(db: Session, supplier_id: int) -> Supplier:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise AppError(400, "INVALID_SUPPLIER", "Supplier does not exist")
    if not supplier.is_active:
        raise AppError(400, "INACTIVE_SUPPLIER", f"Supplier {supplier.name} is inactive")
    return supplier


def _active_warehouse(db: Session, warehouse_id: int) -> Warehouse:
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise AppError(400, "INVALID_WAREHOUSE", "Warehouse does not exist")
    if not warehouse.is_active:
        raise AppError(400, "INACTIVE_WAREHOUSE", f"Warehouse {warehouse.name} is inactive")
    return warehouse


def _active_products(db: Session, product_ids: list[int]) -> None:
    if len(product_ids) != len(set(product_ids)):
        raise AppError(400, "DUPLICATE_LINE", "Each product may appear only once per order")
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(product_ids)))}
    for pid in product_ids:
        product = products.get(pid)
        if product is None:
            raise AppError(400, "INVALID_PRODUCT", f"Product {pid} does not exist")
        if not product.is_active:
            raise AppError(400, "INACTIVE_PRODUCT", f"Product {product.code} is inactive")


def _lock_po(db: Session, po_id: int) -> PurchaseOrder:
    po = db.scalar(
        select(PurchaseOrder)
        .where(PurchaseOrder.id == po_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if po is None:
        raise AppError(404, "PO_NOT_FOUND", "Purchase order not found")
    return po


def _lock_grn(db: Session, grn_id: int) -> GoodsReceipt:
    grn = db.scalar(
        select(GoodsReceipt)
        .where(GoodsReceipt.id == grn_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if grn is None:
        raise AppError(404, "RECEIPT_NOT_FOUND", "Goods receipt not found")
    return grn


def _require_status(po: PurchaseOrder, allowed: Iterable[str], action: str) -> None:
    if po.status not in allowed:
        nice = po.status.replace("_", " ")
        raise AppError(400, "INVALID_STATUS", f"Cannot {action} {po.po_number}: it is {nice}")


# =========================================================================================
# Purchase orders
# =========================================================================================


def _apply_po_data(db: Session, po: PurchaseOrder, data: PoIn) -> None:
    """Validate and copy header + lines onto `po` (new or draft being edited)."""
    _active_supplier(db, data.supplier_id)
    _active_warehouse(db, data.warehouse_id)
    _active_products(db, [i.product_id for i in data.items])
    items = [
        PurchaseOrderItem(
            product_id=i.product_id,
            qty=i.qty,
            unit_cost=i.unit_cost,
            line_total=_money(i.qty * i.unit_cost),
            received_qty=ZERO,
        )
        for i in data.items
    ]
    subtotal = sum((i.line_total for i in items), ZERO)
    if data.discount > subtotal:
        raise AppError(400, "INVALID_DISCOUNT", "Discount cannot be more than the subtotal")
    po.supplier_id = data.supplier_id
    po.warehouse_id = data.warehouse_id
    po.order_date = data.order_date or today()
    po.expected_date = data.expected_date
    po.notes = data.notes
    po.subtotal = subtotal
    po.discount = data.discount
    po.total = subtotal - data.discount
    po.items = items


def create_po(db: Session, user: User, data: PoIn, request: Request | None = None) -> PurchaseOrder:
    with atomic(db):
        po = PurchaseOrder(
            po_number=next_document_number(db, "PO"), status=DRAFT, created_by=user.id
        )
        _apply_po_data(db, po, data)
        db.add(po)
        db.flush()
        log_audit(
            db,
            user,
            "create",
            "purchase_order",
            po.id,
            f"Created {po.po_number}",
            new=data.model_dump(),
            request=request,
        )
    return po


def update_po(
    db: Session, user: User, po_id: int, data: PoIn, request: Request | None = None
) -> PurchaseOrder:
    with atomic(db):
        po = _lock_po(db, po_id)
        _require_status(po, (DRAFT,), "edit")
        old = {
            "supplier_id": po.supplier_id,
            "warehouse_id": po.warehouse_id,
            "total": po.total,
            "lines": len(po.items),
        }
        _apply_po_data(db, po, data)
        db.flush()
        log_audit(
            db,
            user,
            "update",
            "purchase_order",
            po.id,
            f"Updated {po.po_number}",
            old=old,
            new=data.model_dump(),
            request=request,
        )
    return po


def _mark_approved(po: PurchaseOrder, user: User) -> None:
    po.status = APPROVED
    po.approved_by = user.id
    po.approved_at = utcnow()


def approve_po(
    db: Session, user: User, po_id: int, request: Request | None = None
) -> PurchaseOrder:
    """Finalize a draft: approved, or pending_approval when an approval rule applies."""
    with atomic(db):
        po = _lock_po(db, po_id)
        _require_status(po, (DRAFT,), "approve")
        if approvals.maybe_require_approval(
            db, PURCHASE_ORDER, po.id, po.po_number, po.total, user, request
        ):
            po.status = PENDING_APPROVAL
            summary = f"Submitted {po.po_number} for approval"
        else:
            _mark_approved(po, user)
            summary = f"Approved {po.po_number}"
        log_audit(
            db,
            user,
            "approve",
            "purchase_order",
            po.id,
            summary,
            new={"status": po.status},
            request=request,
        )
    return po


def finalize_po_approval(
    db: Session, po_id: int, user: User, request: Request | None = None
) -> PurchaseOrder:
    """Entry point for the approvals module once a pending PO is approved."""
    with atomic(db):
        po = _lock_po(db, po_id)
        _require_status(po, (PENDING_APPROVAL,), "approve")
        _mark_approved(po, user)
        log_audit(
            db,
            user,
            "approve",
            "purchase_order",
            po.id,
            f"Approved {po.po_number}",
            new={"status": po.status},
            request=request,
        )
    return po


def reject_po(
    db: Session, po_id: int, user: User, remark: str, request: Request | None = None
) -> PurchaseOrder:
    """Approvals module: a pending PO was rejected. Final - it can only be cancelled."""
    with atomic(db):
        po = _lock_po(db, po_id)
        _require_status(po, (PENDING_APPROVAL,), "reject")
        po.status = REJECTED
        log_audit(
            db,
            user,
            "reject",
            "purchase_order",
            po.id,
            f"Rejected {po.po_number}: {remark}",
            old={"status": PENDING_APPROVAL},
            new={"status": REJECTED},
            request=request,
        )
    return po


approvals.register(PURCHASE_ORDER, finalize_po_approval, reject_po)


def cancel_po(db: Session, user: User, po_id: int, request: Request | None = None) -> PurchaseOrder:
    with atomic(db):
        po = _lock_po(db, po_id)
        if po.status in (PARTIALLY_RECEIVED, RECEIVED) or any(i.received_qty > 0 for i in po.items):
            raise AppError(
                400, "CANNOT_CANCEL", f"{po.po_number} has received goods and cannot be cancelled"
            )
        _require_status(po, (DRAFT, PENDING_APPROVAL, APPROVED, REJECTED), "cancel")
        old = po.status
        if old == PENDING_APPROVAL:
            approvals.close_request(db, PURCHASE_ORDER, po.id, user)
        po.status = CANCELLED
        log_audit(
            db,
            user,
            "cancel",
            "purchase_order",
            po.id,
            f"Cancelled {po.po_number}",
            old={"status": old},
            new={"status": CANCELLED},
            request=request,
        )
    return po


# =========================================================================================
# Receiving
# =========================================================================================


def _receive(
    db: Session,
    user: User,
    po: PurchaseOrder,
    lines: list[tuple[PurchaseOrderItem, Decimal, Decimal]],
    receipt_date: date,
    notes: str,
    is_direct: bool,
    request: Request | None,
) -> GoodsReceipt:
    """Post a receipt for (po_item, qty, unit_cost) lines inside the caller's transaction.
    `po` must already be locked."""
    grn = GoodsReceipt(
        grn_number=next_document_number(db, "GRN"),
        po_id=po.id,
        supplier_id=po.supplier_id,
        warehouse_id=po.warehouse_id,
        receipt_date=receipt_date,
        subtotal=ZERO,
        discount=ZERO,
        total=ZERO,
        is_direct=is_direct,
        notes=notes,
        created_by=user.id,
    )
    db.add(grn)
    db.flush()

    po_value = ZERO  # received qty valued at PO cost: basis for the discount share
    for po_item, qty, cost in lines:
        remaining = po_item.qty - po_item.received_qty
        if qty > remaining:
            raise AppError(
                400,
                "OVER_RECEIPT",
                f"Cannot receive {qty.normalize():f} of line {po_item.id}: "
                f"only {remaining.normalize():f} remaining on {po.po_number}",
            )
        line = GoodsReceiptItem(
            po_item_id=po_item.id,
            product_id=po_item.product_id,
            qty=qty,
            unit_cost=cost,
            line_total=_money(qty * cost),
            returned_qty=ZERO,
        )
        grn.items.append(line)
        inventory.stock_in(
            db,
            po_item.product_id,
            po.warehouse_id,
            qty,
            cost,
            PURCHASE_IN,
            GOODS_RECEIPT,
            grn.id,
            receipt_date,
            user,
            f"{grn.grn_number} / {po.po_number}",
        )
        po_item.received_qty += qty
        po_value += qty * po_item.unit_cost

    # Compute subtotal/discount/total first and assign them together: the DB checks
    # total = subtotal - discount on every flush (queries below autoflush).
    subtotal = sum((i.line_total for i in grn.items), ZERO)
    discount = ZERO
    complete = all(i.received_qty >= i.qty for i in po.items)
    if po.discount > 0:
        given = db.scalar(
            select(func.coalesce(func.sum(GoodsReceipt.discount), 0)).where(
                GoodsReceipt.po_id == po.id, GoodsReceipt.id != grn.id
            )
        )
        left = po.discount - Decimal(given or 0)
        # The receipt completing the PO takes the exact remainder so shares add up.
        share = left if complete else _money(po.discount * po_value / po.subtotal)
        discount = max(ZERO, min(share, left, subtotal))
    grn.subtotal, grn.discount, grn.total = subtotal, discount, subtotal - discount

    po.status = RECEIVED if complete else PARTIALLY_RECEIVED
    if grn.total > 0:
        parties.post_party_entry(
            db,
            SUPPLIER,
            po.supplier_id,
            receipt_date,
            ZERO,
            grn.total,
            GOODS_RECEIPT,
            grn.id,
            f"{grn.grn_number} (PO {po.po_number})",
            user,
        )
    db.flush()
    log_audit(
        db,
        user,
        "post",
        "goods_receipt",
        grn.id,
        f"Received {grn.grn_number} for {po.po_number}: {grn.total:.2f}",
        new={
            "po_id": po.id,
            "subtotal": grn.subtotal,
            "discount": grn.discount,
            "total": grn.total,
            "lines": len(grn.items),
        },
        request=request,
    )
    return grn


def receive_goods(
    db: Session, user: User, po_id: int, data: ReceiveIn, request: Request | None = None
) -> GoodsReceipt:
    with atomic(db):
        po = _lock_po(db, po_id)
        _require_status(po, (APPROVED, PARTIALLY_RECEIVED), "receive goods for")
        by_id = {i.id: i for i in po.items}
        ids = [i.po_item_id for i in data.items]
        if len(ids) != len(set(ids)):
            raise AppError(400, "DUPLICATE_LINE", "Each order line may appear only once")
        lines = []
        for item in data.items:
            po_item = by_id.get(item.po_item_id)
            if po_item is None:
                raise AppError(
                    400, "INVALID_LINE", f"Line {item.po_item_id} is not on {po.po_number}"
                )
            cost = item.unit_cost if item.unit_cost is not None else po_item.unit_cost
            lines.append((po_item, item.qty, cost))
        grn = _receive(
            db, user, po, lines, data.receipt_date or today(), data.notes, False, request
        )
    return grn


def direct_purchase(
    db: Session, user: User, data: DirectPurchaseIn, request: Request | None = None
) -> PurchaseOrder:
    """Create a PO and receive it in full, in one transaction."""
    with atomic(db):
        po = PurchaseOrder(
            po_number=next_document_number(db, "PO"), status=DRAFT, created_by=user.id
        )
        _apply_po_data(db, po, data)
        db.add(po)
        db.flush()
        log_audit(
            db,
            user,
            "create",
            "purchase_order",
            po.id,
            f"Direct purchase {po.po_number}",
            new=data.model_dump(),
            request=request,
        )
        # Above an approval threshold nothing is received: the PO waits for approval and
        # is received normally afterwards.
        if approvals.maybe_require_approval(
            db, PURCHASE_ORDER, po.id, po.po_number, po.total, user, request
        ):
            po.status = PENDING_APPROVAL
            return po
        _mark_approved(po, user)
        _receive(
            db,
            user,
            po,
            [(i, i.qty, i.unit_cost) for i in po.items],
            po.order_date,
            po.notes,
            True,
            request,
        )
    return po


# =========================================================================================
# Returns
# =========================================================================================


def purchase_return(
    db: Session, user: User, grn_id: int, data: ReturnIn, request: Request | None = None
) -> PurchaseReturn:
    with atomic(db):
        grn = _lock_grn(db, grn_id)
        by_id = {i.id: i for i in grn.items}
        ids = [i.grn_item_id for i in data.items]
        if len(ids) != len(set(ids)):
            raise AppError(400, "DUPLICATE_LINE", "Each receipt line may appear only once")
        when = data.return_date or today()
        ret = PurchaseReturn(
            prn_number=next_document_number(db, "PRN"),
            goods_receipt_id=grn.id,
            supplier_id=grn.supplier_id,
            warehouse_id=grn.warehouse_id,
            return_date=when,
            subtotal=ZERO,
            discount=ZERO,
            total=ZERO,
            notes=data.notes,
            created_by=user.id,
        )
        db.add(ret)
        db.flush()
        for item in data.items:
            line = by_id.get(item.grn_item_id)
            if line is None:
                raise AppError(
                    400, "INVALID_LINE", f"Line {item.grn_item_id} is not on {grn.grn_number}"
                )
            returnable = line.qty - line.returned_qty
            if item.qty > returnable:
                raise AppError(
                    400,
                    "OVER_RETURN",
                    f"Cannot return {item.qty.normalize():f} of line {line.id}: only "
                    f"{returnable.normalize():f} returnable on {grn.grn_number}",
                )
            # OUT at the original receipt cost; the engine recomputes the average from value.
            inventory.stock_out(
                db,
                line.product_id,
                grn.warehouse_id,
                item.qty,
                PURCHASE_RETURN_OUT,
                PURCHASE_RETURN,
                ret.id,
                when,
                user,
                unit_cost=line.unit_cost,
                note=f"{ret.prn_number} / {grn.grn_number}",
            )
            line.returned_qty += item.qty
            ret.items.append(
                PurchaseReturnItem(
                    grn_item_id=line.id,
                    product_id=line.product_id,
                    qty=item.qty,
                    unit_cost=line.unit_cost,
                    line_total=_money(item.qty * line.unit_cost),
                )
            )
        subtotal = sum((i.line_total for i in ret.items), ZERO)
        discount = ZERO
        if grn.discount > 0 and grn.subtotal > 0:
            given = db.scalar(
                select(func.coalesce(func.sum(PurchaseReturn.discount), 0)).where(
                    PurchaseReturn.goods_receipt_id == grn.id, PurchaseReturn.id != ret.id
                )
            )
            share = _money(subtotal * grn.discount / grn.subtotal)
            discount = max(ZERO, min(share, grn.discount - Decimal(given or 0), subtotal))
        ret.subtotal, ret.discount, ret.total = subtotal, discount, subtotal - discount
        if ret.total > 0:
            parties.post_party_entry(
                db,
                SUPPLIER,
                grn.supplier_id,
                when,
                ret.total,
                ZERO,
                PURCHASE_RETURN,
                ret.id,
                f"{ret.prn_number} (return of {grn.grn_number})",
                user,
            )
        db.flush()
        log_audit(
            db,
            user,
            "post",
            "purchase_return",
            ret.id,
            f"Returned {ret.prn_number} against {grn.grn_number}: {ret.total:.2f}",
            new={
                "goods_receipt_id": grn.id,
                "subtotal": ret.subtotal,
                "discount": ret.discount,
                "total": ret.total,
            },
            request=request,
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

    def __init__(
        self,
        db: Session,
        products: Iterable[int],
        suppliers: Iterable[int],
        warehouses: Iterable[int],
        users: Iterable[int | None],
    ) -> None:
        self.products = _by_id(db, Product, products)
        self.units = _by_id(db, Unit, [p.unit_id for p in self.products.values()])
        self.suppliers = _by_id(db, Supplier, suppliers)
        self.warehouses = _by_id(db, Warehouse, warehouses)
        self.users = _by_id(db, User, users)

    def line(self, item: Any) -> dict[str, Any]:
        p = self.products[item.product_id]
        return {
            "id": item.id,
            "product_id": p.id,
            "product_code": p.code,
            "product_name": p.name,
            "unit_code": self.units[p.unit_id].short_code,
        }

    def user(self, user_id: int | None) -> str | None:
        return self.users[user_id].full_name if user_id in self.users else None


def _names_for(
    db: Session,
    pos: list[PurchaseOrder] = (),
    grns: list[GoodsReceipt] = (),
    rets: list[PurchaseReturn] = (),
) -> _Names:
    docs: list[Any] = [*pos, *grns, *rets]
    return _Names(
        db,
        products=[i.product_id for d in docs for i in d.items],
        suppliers=[d.supplier_id for d in docs],
        warehouses=[d.warehouse_id for d in docs],
        users=[u for d in docs for u in (d.created_by, getattr(d, "approved_by", None))],
    )


def return_out(
    ret: PurchaseReturn, names: _Names, grn: GoodsReceipt, po: PurchaseOrder | None
) -> dict[str, Any]:
    return {
        "id": ret.id,
        "prn_number": ret.prn_number,
        "goods_receipt_id": grn.id,
        "grn_number": grn.grn_number,
        "po_id": po.id if po else None,
        "po_number": po.po_number if po else None,
        "supplier_id": ret.supplier_id,
        "supplier_name": names.suppliers[ret.supplier_id].name,
        "warehouse_id": ret.warehouse_id,
        "warehouse_name": names.warehouses[ret.warehouse_id].name,
        "return_date": ret.return_date,
        "subtotal": ret.subtotal,
        "discount": ret.discount,
        "total": ret.total,
        "notes": ret.notes,
        "created_by_name": names.user(ret.created_by) or "",
        "created_at": ret.created_at,
        "items": [
            names.line(i)
            | {
                "grn_item_id": i.grn_item_id,
                "qty": i.qty,
                "unit_cost": i.unit_cost,
                "line_total": i.line_total,
            }
            for i in ret.items
        ],
    }


def receipt_out(
    db: Session, grn: GoodsReceipt, names: _Names | None = None, po: PurchaseOrder | None = None
) -> dict[str, Any]:
    rets = list(
        db.scalars(
            select(PurchaseReturn)
            .where(PurchaseReturn.goods_receipt_id == grn.id)
            .order_by(PurchaseReturn.id)
        )
    )
    names = names or _names_for(db, grns=[grn], rets=rets)
    if rets and any(r.created_by not in names.users for r in rets):
        names = _names_for(db, grns=[grn], rets=rets)
    po = po or (db.get(PurchaseOrder, grn.po_id) if grn.po_id else None)
    return {
        "id": grn.id,
        "grn_number": grn.grn_number,
        "po_id": po.id if po else None,
        "po_number": po.po_number if po else None,
        "supplier_id": grn.supplier_id,
        "supplier_name": names.suppliers[grn.supplier_id].name,
        "warehouse_id": grn.warehouse_id,
        "warehouse_name": names.warehouses[grn.warehouse_id].name,
        "receipt_date": grn.receipt_date,
        "subtotal": grn.subtotal,
        "discount": grn.discount,
        "total": grn.total,
        "is_direct": grn.is_direct,
        "notes": grn.notes,
        "created_by_name": names.user(grn.created_by) or "",
        "created_at": grn.created_at,
        "items": [
            names.line(i)
            | {
                "po_item_id": i.po_item_id,
                "qty": i.qty,
                "unit_cost": i.unit_cost,
                "line_total": i.line_total,
                "returned_qty": i.returned_qty,
                "returnable_qty": i.qty - i.returned_qty,
            }
            for i in grn.items
        ],
        "returns": [return_out(r, names, grn, po) for r in rets],
    }


def po_out(po: PurchaseOrder, names: _Names) -> dict[str, Any]:
    supplier = names.suppliers[po.supplier_id]
    return {
        "id": po.id,
        "po_number": po.po_number,
        "supplier_id": supplier.id,
        "supplier_code": supplier.code,
        "supplier_name": supplier.name,
        "warehouse_id": po.warehouse_id,
        "warehouse_name": names.warehouses[po.warehouse_id].name,
        "order_date": po.order_date,
        "expected_date": po.expected_date,
        "status": po.status,
        "subtotal": po.subtotal,
        "discount": po.discount,
        "total": po.total,
        "notes": po.notes,
        "created_by_name": names.user(po.created_by) or "",
        "approved_by_name": names.user(po.approved_by),
        "approved_at": po.approved_at,
        "created_at": po.created_at,
        "items": [
            names.line(i)
            | {
                "qty": i.qty,
                "unit_cost": i.unit_cost,
                "line_total": i.line_total,
                "received_qty": i.received_qty,
                "remaining_qty": i.qty - i.received_qty,
            }
            for i in po.items
        ],
    }


def get_po(db: Session, po_id: int) -> PurchaseOrder:
    po = db.get(PurchaseOrder, po_id)
    if po is None:
        raise AppError(404, "PO_NOT_FOUND", "Purchase order not found")
    return po


def po_detail(db: Session, po: PurchaseOrder) -> dict[str, Any]:
    db.refresh(po)
    grns = list(
        db.scalars(
            select(GoodsReceipt).where(GoodsReceipt.po_id == po.id).order_by(GoodsReceipt.id)
        )
    )
    names = _names_for(db, pos=[po], grns=grns)
    return po_out(po, names) | {
        "receipts": [receipt_out(db, g, names, po) for g in grns],
        "supplier_due": parties.get_balance(db, SUPPLIER, po.supplier_id),
    }


def _page(db: Session, stmt: Any, params: PageParams) -> tuple[int, list[Any]]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    return total, list(db.scalars(stmt.limit(params.page_size).offset(params.offset)))


def list_pos(
    db: Session,
    params: PageParams,
    supplier_id: int | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    stmt = select(PurchaseOrder).order_by(PurchaseOrder.id.desc())
    if supplier_id is not None:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
    if date_from:
        stmt = stmt.where(PurchaseOrder.order_date >= date_from)
    if date_to:
        stmt = stmt.where(PurchaseOrder.order_date <= date_to)
    if params.search:
        stmt = stmt.join(Supplier, Supplier.id == PurchaseOrder.supplier_id).where(
            or_(
                PurchaseOrder.po_number.contains(params.search, autoescape=True),
                Supplier.name.contains(params.search, autoescape=True),
            )
        )
    total, pos = _page(db, stmt, params)
    names = _names_for(db, pos=pos)
    return {
        "items": [po_out(p, names) for p in pos],
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
    }


def get_receipt(db: Session, grn_id: int) -> GoodsReceipt:
    grn = db.get(GoodsReceipt, grn_id)
    if grn is None:
        raise AppError(404, "RECEIPT_NOT_FOUND", "Goods receipt not found")
    return grn


def list_receipts(
    db: Session,
    params: PageParams,
    supplier_id: int | None = None,
    po_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    stmt = select(GoodsReceipt).order_by(GoodsReceipt.id.desc())
    if supplier_id is not None:
        stmt = stmt.where(GoodsReceipt.supplier_id == supplier_id)
    if po_id is not None:
        stmt = stmt.where(GoodsReceipt.po_id == po_id)
    if date_from:
        stmt = stmt.where(GoodsReceipt.receipt_date >= date_from)
    if date_to:
        stmt = stmt.where(GoodsReceipt.receipt_date <= date_to)
    if params.search:
        stmt = stmt.where(GoodsReceipt.grn_number.contains(params.search, autoescape=True))
    total, grns = _page(db, stmt, params)
    return {
        "items": [receipt_out(db, g) for g in grns],
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
    }


def get_return(db: Session, ret_id: int) -> PurchaseReturn:
    ret = db.get(PurchaseReturn, ret_id)
    if ret is None:
        raise AppError(404, "RETURN_NOT_FOUND", "Purchase return not found")
    return ret


def return_detail(db: Session, ret: PurchaseReturn) -> dict[str, Any]:
    grn = db.get(GoodsReceipt, ret.goods_receipt_id)
    assert grn is not None
    po = db.get(PurchaseOrder, grn.po_id) if grn.po_id else None
    return return_out(ret, _names_for(db, rets=[ret]), grn, po)


def list_returns(
    db: Session,
    params: PageParams,
    supplier_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    stmt = select(PurchaseReturn).order_by(PurchaseReturn.id.desc())
    if supplier_id is not None:
        stmt = stmt.where(PurchaseReturn.supplier_id == supplier_id)
    if date_from:
        stmt = stmt.where(PurchaseReturn.return_date >= date_from)
    if date_to:
        stmt = stmt.where(PurchaseReturn.return_date <= date_to)
    if params.search:
        stmt = stmt.where(PurchaseReturn.prn_number.contains(params.search, autoescape=True))
    total, rets = _page(db, stmt, params)
    return {
        "items": [return_detail(db, r) for r in rets],
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
    }
