"""Inventory engine + stock documents.

Engine functions (stock_in, stock_out, reserve, release, transfer, reverse_transaction) run
inside the caller's transaction and never commit. Every change to a stock_balances row
happens under SELECT ... FOR UPDATE; multi-row operations lock rows in sorted
(product_id, warehouse_id) order so concurrent postings cannot deadlock each other.

Costing (docs/BUSINESS_RULES.md): weighted average per product per warehouse.
"""

from collections.abc import Iterable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.dates import today
from app.core.db import atomic, utcnow
from app.core.errors import AppError
from app.core.numbering import next_document_number
from app.core.pagination import PageParams
from app.modules.approvals import service as approvals
from app.modules.approvals.models import STOCK_ADJUSTMENT
from app.modules.auth.models import User
from app.modules.inventory.models import (
    ADJUST_IN,
    ADJUST_OUT,
    CANCELLED,
    COUNT_IN,
    COUNT_OUT,
    DRAFT,
    IN_TYPES,
    INCREASE,
    OPENING,
    OUT_TYPES,
    PENDING_APPROVAL,
    POSTED,
    PURCHASE_IN,
    PURCHASE_RETURN_OUT,
    REJECTED,
    SALE_OUT,
    SALE_RETURN_IN,
    TRANSFER_IN,
    TRANSFER_OUT,
    StockAdjustment,
    StockAdjustmentItem,
    StockBalance,
    StockCount,
    StockCountItem,
    StockTransaction,
    StockTransfer,
    StockTransferItem,
)
from app.modules.inventory.schemas import (
    AdjustmentIn,
    CountIn,
    TransferIn,
)
from app.modules.master.models import Category, Product, Unit, Warehouse

Q2 = Decimal("0.01")
Q3 = Decimal("0.001")
Q4 = Decimal("0.0001")
ZERO = Decimal("0")

REVERSAL = "REVERSAL"
# Opposite movement used when reversing a ledger row.
REVERSE_TYPE = {
    ADJUST_IN: ADJUST_OUT,
    ADJUST_OUT: ADJUST_IN,
    COUNT_IN: COUNT_OUT,
    COUNT_OUT: COUNT_IN,
    TRANSFER_IN: TRANSFER_OUT,
    TRANSFER_OUT: TRANSFER_IN,
    PURCHASE_IN: PURCHASE_RETURN_OUT,
    PURCHASE_RETURN_OUT: PURCHASE_IN,
    SALE_OUT: SALE_RETURN_IN,
    SALE_RETURN_IN: SALE_OUT,
    OPENING: ADJUST_OUT,
}


# =========================================================================================
# Validation helpers
# =========================================================================================


def _qty(value: Any) -> Decimal:
    qty = Decimal(value)
    if not qty.is_finite() or qty <= 0 or qty != qty.quantize(Q3):
        raise AppError(400, "INVALID_QTY", "Quantity must be more than 0 with at most 3 decimals")
    return qty


def _cost(value: Any) -> Decimal:
    cost = Decimal(value)
    if not cost.is_finite() or cost < 0 or cost != cost.quantize(Q4):
        raise AppError(400, "INVALID_COST", "Unit cost must be 0 or more with at most 4 decimals")
    return cost


def _fmt(qty: Decimal) -> str:
    return f"{qty.normalize():f}"


def _where(db: Session, balance: "StockBalance") -> str:
    """'P-0001 Plastic Granules in Main Warehouse' for error messages."""
    product = db.get(Product, balance.product_id)
    warehouse = db.get(Warehouse, balance.warehouse_id)
    p = f"{product.code} {product.name}" if product else f"product {balance.product_id}"
    w = warehouse.name if warehouse else f"warehouse {balance.warehouse_id}"
    return f"{p} in {w}"


# =========================================================================================
# Balance row locking
# =========================================================================================


def _select_for_update(db: Session, product_id: int, warehouse_id: int) -> StockBalance | None:
    return db.scalar(
        select(StockBalance)
        .where(StockBalance.product_id == product_id, StockBalance.warehouse_id == warehouse_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _lock_balance(db: Session, product_id: int, warehouse_id: int) -> StockBalance:
    """Return the balance row locked FOR UPDATE, creating it (zeroes) if missing.

    A plain read decides whether to insert; locking a missing row with FOR UPDATE first
    would take gap locks that make two concurrent creators deadlock. The insert uses
    ON DUPLICATE KEY UPDATE so a concurrent creator simply turns it into a no-op.
    """
    exists = db.scalar(
        select(StockBalance.id).where(
            StockBalance.product_id == product_id, StockBalance.warehouse_id == warehouse_id
        )
    )
    if exists is None:
        if db.get(Product, product_id) is None:
            raise AppError(400, "INVALID_PRODUCT", f"Product {product_id} does not exist")
        if db.get(Warehouse, warehouse_id) is None:
            raise AppError(400, "INVALID_WAREHOUSE", f"Warehouse {warehouse_id} does not exist")
        stmt = mysql_insert(StockBalance).values(
            product_id=product_id,
            warehouse_id=warehouse_id,
            qty_on_hand=ZERO,
            qty_reserved=ZERO,
            avg_cost=ZERO,
        )
        db.execute(stmt.on_duplicate_key_update(id=StockBalance.__table__.c.id))
    balance = _select_for_update(db, product_id, warehouse_id)
    assert balance is not None
    return balance


def _lock_balances(
    db: Session, keys: Iterable[tuple[int, int]]
) -> dict[tuple[int, int], StockBalance]:
    """Lock several (product_id, warehouse_id) rows in a fixed order (deadlock-free)."""
    return {key: _lock_balance(db, *key) for key in sorted(set(keys))}


def get_balance(db: Session, product_id: int, warehouse_id: int) -> StockBalance | None:
    """Unlocked read (for display / snapshots)."""
    return db.scalar(
        select(StockBalance)
        .where(StockBalance.product_id == product_id, StockBalance.warehouse_id == warehouse_id)
        .execution_options(populate_existing=True)
    )


# =========================================================================================
# Engine
# =========================================================================================


def _ledger(
    db: Session,
    balance: StockBalance,
    txn_type: str,
    qty_in: Decimal,
    qty_out: Decimal,
    unit_cost: Decimal,
    ref_type: str,
    ref_id: int | None,
    txn_date: date,
    user: User,
    note: str,
    reversal_of_id: int | None = None,
) -> StockTransaction:
    row = StockTransaction(
        product_id=balance.product_id,
        warehouse_id=balance.warehouse_id,
        txn_type=txn_type,
        qty_in=qty_in,
        qty_out=qty_out,
        unit_cost=unit_cost,
        balance_after=balance.qty_on_hand,
        ref_type=ref_type,
        ref_id=ref_id,
        txn_date=txn_date,
        note=note[:255],
        reversal_of_id=reversal_of_id,
        created_by=user.id,
    )
    db.add(row)
    db.flush()
    return row


def stock_in(
    db: Session,
    product_id: int,
    warehouse_id: int,
    qty: Any,
    unit_cost: Any,
    txn_type: str,
    ref_type: str,
    ref_id: int | None,
    txn_date: date,
    user: User,
    note: str = "",
    reversal_of_id: int | None = None,
) -> StockTransaction:
    """Receive stock at `unit_cost`; updates on_hand and the weighted average cost:
    new_avg = (on_hand*avg + qty*cost) / (on_hand + qty), rounded to 4 places."""
    if txn_type not in IN_TYPES:
        raise ValueError(f"{txn_type} is not an IN transaction type")
    qty, cost = _qty(qty), _cost(unit_cost)
    balance = _lock_balance(db, product_id, warehouse_id)
    new_qty = balance.qty_on_hand + qty
    value = balance.qty_on_hand * balance.avg_cost + qty * cost
    balance.avg_cost = (value / new_qty).quantize(Q4, ROUND_HALF_UP)
    balance.qty_on_hand = new_qty
    return _ledger(
        db,
        balance,
        txn_type,
        qty,
        ZERO,
        cost,
        ref_type,
        ref_id,
        txn_date,
        user,
        note,
        reversal_of_id,
    )


def _take(
    db: Session,
    balance: StockBalance,
    qty: Decimal,
    txn_type: str,
    ref_type: str,
    ref_id: int | None,
    txn_date: date,
    user: User,
    reserved_qty: Decimal = ZERO,
    unit_cost: Decimal | None = None,
    note: str = "",
    reversal_of_id: int | None = None,
) -> StockTransaction:
    """OUT on an already locked balance row."""
    if txn_type not in OUT_TYPES:
        raise ValueError(f"{txn_type} is not an OUT transaction type")
    if reserved_qty < 0 or reserved_qty > qty:
        raise AppError(400, "INVALID_RESERVATION", "Reserved quantity must be between 0 and qty")
    if reserved_qty > balance.qty_reserved:
        raise AppError(
            400,
            "INVALID_RESERVATION",
            f"Only {_fmt(balance.qty_reserved)} is reserved; cannot consume {_fmt(reserved_qty)}",
        )
    free = balance.qty_on_hand - balance.qty_reserved
    if qty - reserved_qty > free:
        raise AppError(
            400,
            "INSUFFICIENT_STOCK",
            f"Insufficient stock of {_where(db, balance)}: available {_fmt(free)}, "
            f"requested {_fmt(qty - reserved_qty)}"
            + (f" (plus {_fmt(reserved_qty)} from reservation)" if reserved_qty else ""),
        )

    remaining = balance.qty_on_hand - qty
    if unit_cost is None:
        cost = balance.avg_cost  # normal OUT: current average, which does not change
    else:
        # OUT at a specific cost (purchase return at receipt cost, reversal of an IN):
        # take that value out so the remaining stock keeps its true value.
        cost = _cost(unit_cost)
        if remaining > 0:
            value = balance.qty_on_hand * balance.avg_cost - qty * cost
            balance.avg_cost = max(ZERO, (value / remaining).quantize(Q4, ROUND_HALF_UP))
    balance.qty_reserved -= reserved_qty
    balance.qty_on_hand = remaining
    return _ledger(
        db,
        balance,
        txn_type,
        ZERO,
        qty,
        cost,
        ref_type,
        ref_id,
        txn_date,
        user,
        note,
        reversal_of_id,
    )


def stock_out(
    db: Session,
    product_id: int,
    warehouse_id: int,
    qty: Any,
    txn_type: str,
    ref_type: str,
    ref_id: int | None,
    txn_date: date,
    user: User,
    reserved_qty: Any = ZERO,
    unit_cost: Any | None = None,
    note: str = "",
) -> Decimal:
    """Issue stock; returns the unit cost used (COGS per unit).

    `reserved_qty` of the quantity comes from the caller's own reservation (it is released
    as consumed); the rest must be free stock (on_hand - reserved). Raises INSUFFICIENT_STOCK
    otherwise. `unit_cost` overrides the average (see _take).
    """
    qty = _qty(qty)
    reserved = Decimal(reserved_qty)
    balance = _lock_balance(db, product_id, warehouse_id)
    row = _take(
        db,
        balance,
        qty,
        txn_type,
        ref_type,
        ref_id,
        txn_date,
        user,
        reserved,
        None if unit_cost is None else Decimal(unit_cost),
        note,
    )
    return row.unit_cost


def reserve(db: Session, product_id: int, warehouse_id: int, qty: Any) -> StockBalance:
    qty = _qty(qty)
    balance = _lock_balance(db, product_id, warehouse_id)
    available = balance.qty_on_hand - balance.qty_reserved
    if qty > available:
        raise AppError(
            400,
            "INSUFFICIENT_STOCK",
            f"Cannot reserve {_fmt(qty)} of {_where(db, balance)}: "
            f"only {_fmt(available)} available",
        )
    balance.qty_reserved += qty
    db.flush()
    return balance


def reserve_up_to(db: Session, product_id: int, warehouse_id: int, qty: Any) -> Decimal:
    """Reserve min(available, qty) under the row lock; returns the quantity reserved
    (0 when nothing is available). Used for partial reservation of sales orders."""
    qty = _qty(qty)
    balance = _lock_balance(db, product_id, warehouse_id)
    take = max(ZERO, min(qty, balance.qty_on_hand - balance.qty_reserved))
    if take > 0:
        balance.qty_reserved += take
        db.flush()
    return take


def release(db: Session, product_id: int, warehouse_id: int, qty: Any) -> StockBalance:
    qty = _qty(qty)
    balance = _lock_balance(db, product_id, warehouse_id)
    if qty > balance.qty_reserved:
        raise AppError(
            400,
            "INVALID_RELEASE",
            f"Cannot release {_fmt(qty)}: only {_fmt(balance.qty_reserved)} reserved",
        )
    balance.qty_reserved -= qty
    db.flush()
    return balance


def transfer(
    db: Session,
    product_id: int,
    from_warehouse_id: int,
    to_warehouse_id: int,
    qty: Any,
    ref_type: str,
    ref_id: int | None,
    txn_date: date,
    user: User,
    note: str = "",
) -> Decimal:
    """Move stock between warehouses at the source average cost. Returns that cost."""
    if from_warehouse_id == to_warehouse_id:
        raise AppError(400, "SAME_WAREHOUSE", "Source and destination warehouse must differ")
    qty = _qty(qty)
    balances = _lock_balances(db, [(product_id, from_warehouse_id), (product_id, to_warehouse_id)])
    out = _take(
        db,
        balances[(product_id, from_warehouse_id)],
        qty,
        TRANSFER_OUT,
        ref_type,
        ref_id,
        txn_date,
        user,
        note=note,
    )
    stock_in(
        db,
        product_id,
        to_warehouse_id,
        qty,
        out.unit_cost,
        TRANSFER_IN,
        ref_type,
        ref_id,
        txn_date,
        user,
        note,
    )
    return out.unit_cost


def reverse_transaction(
    db: Session, txn_id: int, user: User, txn_date: date | None = None, note: str = ""
) -> StockTransaction:
    """Post the opposite movement of ledger row `txn_id` (the original is never edited)."""
    original = db.get(StockTransaction, txn_id)
    if original is None:
        raise AppError(404, "TXN_NOT_FOUND", "Stock transaction not found")
    if original.reversal_of_id is not None:
        raise AppError(400, "ALREADY_REVERSED", "A reversal entry cannot itself be reversed")
    balance = _lock_balance(db, original.product_id, original.warehouse_id)
    already = db.scalar(
        select(StockTransaction.id).where(StockTransaction.reversal_of_id == original.id)
    )
    if already is not None:
        raise AppError(400, "ALREADY_REVERSED", "This stock transaction was already reversed")

    when = txn_date or today()
    note = note or f"Reversal of stock transaction #{original.id}"
    opposite = REVERSE_TYPE[original.txn_type]
    if original.qty_in > 0:
        return _take(
            db,
            balance,
            original.qty_in,
            opposite,
            REVERSAL,
            original.id,
            when,
            user,
            unit_cost=original.unit_cost,
            note=note,
            reversal_of_id=original.id,
        )
    return stock_in(
        db,
        original.product_id,
        original.warehouse_id,
        original.qty_out,
        original.unit_cost,
        opposite,
        REVERSAL,
        original.id,
        when,
        user,
        note,
        reversal_of_id=original.id,
    )


def _increase_cost(balance: StockBalance, product: Product, given: Decimal | None) -> Decimal:
    """Cost for adjustment/count increases: given cost, else current average, else the
    product's default cost (purchase_price) when the item has never been costed here."""
    if given is not None:
        return _cost(given)
    if balance.avg_cost > 0:
        return balance.avg_cost
    return product.purchase_price


# =========================================================================================
# Documents: shared helpers
# =========================================================================================


def _active_warehouse(db: Session, warehouse_id: int) -> Warehouse:
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise AppError(400, "INVALID_WAREHOUSE", "Warehouse does not exist")
    if not warehouse.is_active:
        raise AppError(400, "INACTIVE_WAREHOUSE", f"Warehouse {warehouse.name} is inactive")
    return warehouse


def _active_products(db: Session, product_ids: list[int]) -> dict[int, Product]:
    if len(product_ids) != len(set(product_ids)):
        raise AppError(400, "DUPLICATE_LINE", "Each product may appear only once per document")
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(product_ids)))}
    for pid in product_ids:
        product = products.get(pid)
        if product is None:
            raise AppError(400, "INVALID_PRODUCT", f"Product {pid} does not exist")
        if not product.is_active:
            raise AppError(400, "INACTIVE_PRODUCT", f"Product {product.code} is inactive")
    return products


def _lock_document(db: Session, model: Any, doc_id: int, label: str) -> Any:
    doc = db.scalar(
        select(model)
        .where(model.id == doc_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if doc is None:
        raise AppError(404, "NOT_FOUND", f"{label} not found")
    return doc


def _ensure_status(doc: Any, allowed: tuple[str, ...], action: str) -> None:
    if doc.status in allowed:
        return
    if doc.status == POSTED:
        raise AppError(400, "ALREADY_POSTED", f"{doc.number} is already posted")
    raise AppError(400, "INVALID_STATUS", f"Cannot {action} {doc.number}: it is {doc.status}")


def _mark_posted(doc: Any, user: User) -> None:
    doc.status = POSTED
    doc.posted_by = user.id
    doc.posted_at = utcnow()


def _cancel(
    db: Session,
    model: Any,
    label: str,
    entity: str,
    doc_id: int,
    user: User,
    request: Request | None,
    allowed: tuple[str, ...] = (DRAFT,),
) -> Any:
    doc = _lock_document(db, model, doc_id, label)
    _ensure_status(doc, allowed, "cancel")
    old = doc.status
    doc.status = CANCELLED
    log_audit(
        db,
        user,
        "cancel",
        entity,
        doc.id,
        f"Cancelled {doc.number}",
        old={"status": old},
        new={"status": CANCELLED},
        request=request,
    )
    db.commit()
    return doc


# =========================================================================================
# Transfers
# =========================================================================================


def create_transfer(
    db: Session, user: User, data: TransferIn, request: Request | None = None
) -> StockTransfer:
    if data.from_warehouse_id == data.to_warehouse_id:
        raise AppError(400, "SAME_WAREHOUSE", "Source and destination warehouse must differ")
    _active_warehouse(db, data.from_warehouse_id)
    _active_warehouse(db, data.to_warehouse_id)
    _active_products(db, [i.product_id for i in data.items])
    doc = StockTransfer(
        number=next_document_number(db, "TRF"),
        from_warehouse_id=data.from_warehouse_id,
        to_warehouse_id=data.to_warehouse_id,
        transfer_date=data.transfer_date or today(),
        note=data.note,
        status=DRAFT,
        created_by=user.id,
        items=[StockTransferItem(product_id=i.product_id, qty=i.qty) for i in data.items],
    )
    db.add(doc)
    db.flush()
    log_audit(
        db,
        user,
        "create",
        "stock_transfer",
        doc.id,
        f"Created transfer {doc.number}",
        new=data.model_dump(),
        request=request,
    )
    db.commit()
    return doc


def post_transfer(
    db: Session, transfer_id: int, user: User, request: Request | None = None
) -> StockTransfer:
    with atomic(db):
        doc = _lock_document(db, StockTransfer, transfer_id, "Transfer")
        _ensure_status(doc, (DRAFT,), "post")
        keys = [
            (i.product_id, w)
            for i in doc.items
            for w in (doc.from_warehouse_id, doc.to_warehouse_id)
        ]
        balances = _lock_balances(db, keys)
        for item in doc.items:
            out = _take(
                db,
                balances[(item.product_id, doc.from_warehouse_id)],
                item.qty,
                TRANSFER_OUT,
                "STOCK_TRANSFER",
                doc.id,
                doc.transfer_date,
                user,
                note=doc.number,
            )
            stock_in(
                db,
                item.product_id,
                doc.to_warehouse_id,
                item.qty,
                out.unit_cost,
                TRANSFER_IN,
                "STOCK_TRANSFER",
                doc.id,
                doc.transfer_date,
                user,
                doc.number,
            )
            item.unit_cost = out.unit_cost
        _mark_posted(doc, user)
        log_audit(
            db,
            user,
            "post",
            "stock_transfer",
            doc.id,
            f"Posted transfer {doc.number}",
            request=request,
        )
    return doc


def cancel_transfer(
    db: Session, transfer_id: int, user: User, request: Request | None = None
) -> StockTransfer:
    return _cancel(db, StockTransfer, "Transfer", "stock_transfer", transfer_id, user, request)


# =========================================================================================
# Adjustments (create and finalize kept separate so approvals can sit in between)
# =========================================================================================


def create_adjustment(
    db: Session, user: User, data: AdjustmentIn, request: Request | None = None
) -> StockAdjustment:
    _active_warehouse(db, data.warehouse_id)
    _active_products(db, [i.product_id for i in data.items])
    doc = StockAdjustment(
        number=next_document_number(db, "ADJ"),
        warehouse_id=data.warehouse_id,
        adjustment_date=data.adjustment_date or today(),
        reason=data.reason,
        note=data.note,
        status=DRAFT,
        created_by=user.id,
        items=[
            StockAdjustmentItem(
                product_id=i.product_id,
                direction=i.direction,
                qty=i.qty,
                unit_cost=i.unit_cost if i.direction == INCREASE else None,
                note=i.note,
            )
            for i in data.items
        ],
    )
    db.add(doc)
    db.flush()
    log_audit(
        db,
        user,
        "create",
        "stock_adjustment",
        doc.id,
        f"Created adjustment {doc.number}",
        new=data.model_dump(),
        request=request,
    )
    db.commit()
    return doc


def finalize_adjustment(
    db: Session,
    adjustment_id: int,
    user: User,
    request: Request | None = None,
    allowed: tuple[str, ...] = (DRAFT,),
) -> StockAdjustment:
    """Post the stock movements of an adjustment. The approvals module will call this with
    allowed=(PENDING_APPROVAL,) after approval; the post endpoint only accepts drafts."""
    with atomic(db):
        doc = _lock_document(db, StockAdjustment, adjustment_id, "Adjustment")
        _ensure_status(doc, allowed, "post")
        balances = _lock_balances(db, [(i.product_id, doc.warehouse_id) for i in doc.items])
        products = {
            p.id: p
            for p in db.scalars(
                select(Product).where(Product.id.in_([i.product_id for i in doc.items]))
            )
        }
        for item in doc.items:
            balance = balances[(item.product_id, doc.warehouse_id)]
            note = f"{doc.number}: {doc.reason}"
            if item.direction == INCREASE:
                cost = _increase_cost(balance, products[item.product_id], item.unit_cost)
                stock_in(
                    db,
                    item.product_id,
                    doc.warehouse_id,
                    item.qty,
                    cost,
                    ADJUST_IN,
                    "STOCK_ADJUSTMENT",
                    doc.id,
                    doc.adjustment_date,
                    user,
                    note,
                )
            else:
                cost = _take(
                    db,
                    balance,
                    item.qty,
                    ADJUST_OUT,
                    "STOCK_ADJUSTMENT",
                    doc.id,
                    doc.adjustment_date,
                    user,
                    note=note,
                ).unit_cost
            item.unit_cost = cost
        _mark_posted(doc, user)
        log_audit(
            db,
            user,
            "post",
            "stock_adjustment",
            doc.id,
            f"Posted adjustment {doc.number}",
            request=request,
        )
    return doc


def adjustment_value(db: Session, doc: StockAdjustment) -> Decimal:
    """Value used for approval rules: increases at their given cost (or the current
    average / product cost), decreases at the current average."""
    total = ZERO
    for item in doc.items:
        balance = get_balance(db, item.product_id, doc.warehouse_id)
        avg = balance.avg_cost if balance else ZERO
        if item.direction == INCREASE:
            product = db.get(Product, item.product_id)
            cost = item.unit_cost if item.unit_cost is not None else (avg or product.purchase_price)  # type: ignore[union-attr]
        else:
            cost = avg
        total += item.qty * cost
    return total.quantize(Q2, ROUND_HALF_UP)


def submit_adjustment(
    db: Session, adjustment_id: int, user: User, request: Request | None = None
) -> StockAdjustment:
    """ "Post" on a draft: posts it, or - when an approval rule applies to its value - sends
    it for approval and posts nothing."""
    with atomic(db):
        doc = _lock_document(db, StockAdjustment, adjustment_id, "Adjustment")
        _ensure_status(doc, (DRAFT,), "post")
        if approvals.maybe_require_approval(
            db, STOCK_ADJUSTMENT, doc.id, doc.number, adjustment_value(db, doc), user, request
        ):
            doc.status = PENDING_APPROVAL
            return doc
        finalize_adjustment(db, doc.id, user, request)
    return doc


def reject_adjustment(
    db: Session, adjustment_id: int, user: User, remark: str, request: Request | None = None
) -> StockAdjustment:
    """Approvals module: a pending adjustment was rejected. Nothing was posted; it can
    still be cancelled."""
    with atomic(db):
        doc = _lock_document(db, StockAdjustment, adjustment_id, "Adjustment")
        _ensure_status(doc, (PENDING_APPROVAL,), "reject")
        doc.status = REJECTED
        log_audit(
            db,
            user,
            "reject",
            "stock_adjustment",
            doc.id,
            f"Rejected adjustment {doc.number}: {remark}",
            old={"status": PENDING_APPROVAL},
            new={"status": REJECTED},
            request=request,
        )
    return doc


approvals.register(
    STOCK_ADJUSTMENT,
    lambda db, doc_id, user: finalize_adjustment(db, doc_id, user, allowed=(PENDING_APPROVAL,)),
    reject_adjustment,
)


def cancel_adjustment(
    db: Session, adjustment_id: int, user: User, request: Request | None = None
) -> StockAdjustment:
    doc = _lock_document(db, StockAdjustment, adjustment_id, "Adjustment")
    if doc.status == PENDING_APPROVAL:
        approvals.close_request(db, STOCK_ADJUSTMENT, doc.id, user)
    return _cancel(
        db,
        StockAdjustment,
        "Adjustment",
        "stock_adjustment",
        adjustment_id,
        user,
        request,
        allowed=(DRAFT, PENDING_APPROVAL, REJECTED),
    )


# =========================================================================================
# Physical counts
# =========================================================================================


def create_count(
    db: Session, user: User, data: CountIn, request: Request | None = None
) -> StockCount:
    _active_warehouse(db, data.warehouse_id)
    _active_products(db, [i.product_id for i in data.items])
    items = []
    for i in data.items:
        balance = get_balance(db, i.product_id, data.warehouse_id)
        system_qty = balance.qty_on_hand if balance else ZERO
        items.append(
            StockCountItem(
                product_id=i.product_id,
                system_qty=system_qty,
                counted_qty=i.counted_qty,
                variance=i.counted_qty - system_qty,
            )
        )
    doc = StockCount(
        number=next_document_number(db, "CNT"),
        warehouse_id=data.warehouse_id,
        count_date=data.count_date or today(),
        note=data.note,
        status=DRAFT,
        created_by=user.id,
        items=items,
    )
    db.add(doc)
    db.flush()
    log_audit(
        db,
        user,
        "create",
        "stock_count",
        doc.id,
        f"Created count {doc.number}",
        new=data.model_dump(),
        request=request,
    )
    db.commit()
    return doc


def post_count(
    db: Session, count_id: int, user: User, request: Request | None = None
) -> tuple[StockCount, list[int]]:
    """Post each non-zero variance (counted - snapshot) as COUNT_IN / COUNT_OUT.
    Returns the count and the product ids whose stock moved since the snapshot."""
    with atomic(db):
        doc = _lock_document(db, StockCount, count_id, "Count")
        _ensure_status(doc, (DRAFT,), "post")
        balances = _lock_balances(db, [(i.product_id, doc.warehouse_id) for i in doc.items])
        products = {
            p.id: p
            for p in db.scalars(
                select(Product).where(Product.id.in_([i.product_id for i in doc.items]))
            )
        }
        moved = [
            i.product_id
            for i in doc.items
            if balances[(i.product_id, doc.warehouse_id)].qty_on_hand != i.system_qty
        ]
        for item in doc.items:
            balance = balances[(item.product_id, doc.warehouse_id)]
            if item.variance > 0:
                cost = _increase_cost(balance, products[item.product_id], None)
                stock_in(
                    db,
                    item.product_id,
                    doc.warehouse_id,
                    item.variance,
                    cost,
                    COUNT_IN,
                    "STOCK_COUNT",
                    doc.id,
                    doc.count_date,
                    user,
                    doc.number,
                )
                item.unit_cost = cost
            elif item.variance < 0:
                item.unit_cost = _take(
                    db,
                    balance,
                    -item.variance,
                    COUNT_OUT,
                    "STOCK_COUNT",
                    doc.id,
                    doc.count_date,
                    user,
                    note=doc.number,
                ).unit_cost
        _mark_posted(doc, user)
        log_audit(
            db,
            user,
            "post",
            "stock_count",
            doc.id,
            f"Posted count {doc.number}",
            new={"moved_since_snapshot": moved},
            request=request,
        )
    return doc, moved


def cancel_count(
    db: Session, count_id: int, user: User, request: Request | None = None
) -> StockCount:
    return _cancel(db, StockCount, "Count", "stock_count", count_id, user, request)


# =========================================================================================
# Read side: stock list, ledger, document lists/details
# =========================================================================================


def list_stock(
    db: Session,
    params: PageParams,
    warehouse_id: int | None = None,
    product_id: int | None = None,
    category_id: int | None = None,
    product_type: str | None = None,
    low_stock: bool = False,
) -> dict[str, Any]:
    value = StockBalance.qty_on_hand * StockBalance.avg_cost
    conditions = []
    if warehouse_id is not None:
        conditions.append(StockBalance.warehouse_id == warehouse_id)
    if product_id is not None:
        conditions.append(StockBalance.product_id == product_id)
    if category_id is not None:
        conditions.append(Product.category_id == category_id)
    if product_type:
        conditions.append(Product.product_type == product_type)
    if params.search:
        conditions.append(
            or_(
                Product.name.contains(params.search, autoescape=True),
                Product.code.contains(params.search, autoescape=True),
            )
        )
    if low_stock:
        conditions.append(
            and_(Product.reorder_level > 0, StockBalance.qty_on_hand <= Product.reorder_level)
        )
    where = and_(true(), *conditions)
    base = (
        select(StockBalance)
        .join(Product, Product.id == StockBalance.product_id)
        .join(Warehouse, Warehouse.id == StockBalance.warehouse_id)
        .where(where)
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    total_value = db.scalar(
        select(func.coalesce(func.sum(value), 0))
        .select_from(StockBalance)
        .join(Product, Product.id == StockBalance.product_id)
        .where(where)
    )
    rows = db.execute(
        select(StockBalance, Product, Warehouse, Category.name, Unit.short_code)
        .join(Product, Product.id == StockBalance.product_id)
        .join(Warehouse, Warehouse.id == StockBalance.warehouse_id)
        .join(Category, Category.id == Product.category_id)
        .join(Unit, Unit.id == Product.unit_id)
        .where(where)
        .order_by(Product.name, Warehouse.name)
        .limit(params.page_size)
        .offset(params.offset)
    ).all()
    items = [
        {
            "product_id": p.id,
            "product_code": p.code,
            "product_name": p.name,
            "product_type": p.product_type,
            "category_name": cat,
            "unit_code": unit,
            "warehouse_id": w.id,
            "warehouse_name": w.name,
            "qty_on_hand": b.qty_on_hand,
            "qty_reserved": b.qty_reserved,
            "qty_available": b.qty_on_hand - b.qty_reserved,
            "avg_cost": b.avg_cost,
            "value": (b.qty_on_hand * b.avg_cost).quantize(Q2, ROUND_HALF_UP),
            "reorder_level": p.reorder_level,
            "is_low": p.reorder_level > 0 and b.qty_on_hand <= p.reorder_level,
        }
        for b, p, w, cat, unit in rows
    ]
    return {
        "items": items,
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
        "total_value": Decimal(total_value or 0).quantize(Q2, ROUND_HALF_UP),
    }


def stock_ledger(
    db: Session,
    params: PageParams,
    product_id: int,
    warehouse_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    """Ledger rows ordered by (txn_date, id) with opening balance (before `date_from`) and a
    running balance. `balance_after` is the stored per-warehouse balance at posting time."""
    product = db.get(Product, product_id)
    if product is None:
        raise AppError(404, "PRODUCT_NOT_FOUND", "Product not found")
    T = StockTransaction
    scope = [T.product_id == product_id]
    if warehouse_id is not None:
        scope.append(T.warehouse_id == warehouse_id)

    opening = ZERO
    if date_from is not None:
        opening = Decimal(
            db.scalar(
                select(func.coalesce(func.sum(T.qty_in - T.qty_out), 0)).where(
                    *scope, T.txn_date < date_from
                )
            )
            or 0
        )
    in_range = list(scope)
    if date_from is not None:
        in_range.append(T.txn_date >= date_from)
    if date_to is not None:
        in_range.append(T.txn_date <= date_to)

    running = (
        func.sum(T.qty_in - T.qty_out)
        .over(order_by=(T.txn_date, T.id), rows=(None, 0))
        .label("running")
    )
    ranked = select(T.id.label("id"), running).where(*in_range).subquery()
    total = db.scalar(select(func.count()).select_from(ranked)) or 0
    movement = Decimal(
        db.scalar(select(func.coalesce(func.sum(T.qty_in - T.qty_out), 0)).where(*in_range)) or 0
    )
    page_rows = db.execute(
        select(T, ranked.c.running, Warehouse.name)
        .join(ranked, ranked.c.id == T.id)
        .join(Warehouse, Warehouse.id == T.warehouse_id)
        .order_by(T.txn_date, T.id)
        .limit(params.page_size)
        .offset(params.offset)
    ).all()
    users = dict(db.execute(select(User.id, User.full_name)).all()) if page_rows else {}
    items = [
        {
            "id": t.id,
            "txn_date": t.txn_date,
            "txn_type": t.txn_type,
            "warehouse_id": t.warehouse_id,
            "warehouse_name": wname,
            "qty_in": t.qty_in,
            "qty_out": t.qty_out,
            "unit_cost": t.unit_cost,
            "balance_after": t.balance_after,
            "running_balance": opening + Decimal(run),
            "ref_type": t.ref_type,
            "ref_id": t.ref_id,
            "note": t.note,
            "reversal_of_id": t.reversal_of_id,
            "created_by_name": users.get(t.created_by),
            "created_at": t.created_at,
        }
        for t, run, wname in page_rows
    ]
    return {
        "items": items,
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
        "product_id": product.id,
        "product_code": product.code,
        "product_name": product.name,
        "opening_balance": opening,
        "closing_balance": opening + movement,
    }


def _names(db: Session, model: Any, ids: Iterable[int]) -> dict[int, Any]:
    ids = set(ids)
    if not ids:
        return {}
    return {o.id: o for o in db.scalars(select(model).where(model.id.in_(ids)))}


def document_list(
    db: Session,
    model: Any,
    params: PageParams,
    status: str | None,
    warehouse_id: int | None,
) -> dict[str, Any]:
    stmt = select(model).order_by(model.id.desc())
    if status:
        stmt = stmt.where(model.status == status)
    if warehouse_id is not None:
        if model is StockTransfer:
            stmt = stmt.where(
                or_(model.from_warehouse_id == warehouse_id, model.to_warehouse_id == warehouse_id)
            )
        else:
            stmt = stmt.where(model.warehouse_id == warehouse_id)
    if params.search:
        stmt = stmt.where(model.number.contains(params.search, autoescape=True))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    docs = list(db.scalars(stmt.limit(params.page_size).offset(params.offset)))
    return {
        "items": [document_detail(db, d) for d in docs],
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
    }


def document_detail(db: Session, doc: Any) -> dict[str, Any]:
    """Header + items with product/warehouse/user names, as a plain dict for the schemas."""
    warehouse_ids = (
        [doc.from_warehouse_id, doc.to_warehouse_id]
        if isinstance(doc, StockTransfer)
        else [doc.warehouse_id]
    )
    warehouses = _names(db, Warehouse, warehouse_ids)
    products = _names(db, Product, [i.product_id for i in doc.items])
    users = _names(db, User, [u for u in (doc.created_by, doc.posted_by) if u])
    units = _names(db, Unit, [p.unit_id for p in products.values()])
    header: dict[str, Any] = {
        "id": doc.id,
        "number": doc.number,
        "status": doc.status,
        "note": doc.note,
        "created_by_name": users[doc.created_by].full_name,
        "posted_by_name": users[doc.posted_by].full_name if doc.posted_by else None,
        "posted_at": doc.posted_at,
        "created_at": doc.created_at,
    }
    items = []
    for i in doc.items:
        p = products[i.product_id]
        item: dict[str, Any] = {
            "id": i.id,
            "product_id": p.id,
            "product_code": p.code,
            "product_name": p.name,
            "unit_code": units[p.unit_id].short_code,
            "unit_cost": i.unit_cost,
        }
        if isinstance(doc, StockCount):
            current = None
            if doc.status == DRAFT:
                bal = get_balance(db, i.product_id, doc.warehouse_id)
                current = bal.qty_on_hand if bal else ZERO
            item |= {
                "system_qty": i.system_qty,
                "counted_qty": i.counted_qty,
                "variance": i.variance,
                "current_qty": current,
            }
        else:
            item["qty"] = i.qty
            if isinstance(doc, StockAdjustment):
                item |= {"direction": i.direction, "note": i.note}
        items.append(item)
    header["items"] = items

    if isinstance(doc, StockTransfer):
        header |= {
            "from_warehouse_id": doc.from_warehouse_id,
            "from_warehouse_name": warehouses[doc.from_warehouse_id].name,
            "to_warehouse_id": doc.to_warehouse_id,
            "to_warehouse_name": warehouses[doc.to_warehouse_id].name,
            "transfer_date": doc.transfer_date,
        }
    else:
        header |= {
            "warehouse_id": doc.warehouse_id,
            "warehouse_name": warehouses[doc.warehouse_id].name,
        }
        if isinstance(doc, StockAdjustment):
            header |= {"adjustment_date": doc.adjustment_date, "reason": doc.reason}
        else:
            header["count_date"] = doc.count_date
    return header


def get_document(db: Session, model: Any, doc_id: int, label: str) -> Any:
    doc = db.get(model, doc_id)
    if doc is None:
        raise AppError(404, "NOT_FOUND", f"{label} not found")
    return doc
