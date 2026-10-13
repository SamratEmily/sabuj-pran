"""Management dashboard. Every figure is computed live from the documents / ledgers (and
the SQL views over the ledgers), exactly as defined in docs/BUSINESS_RULES.md:

- Today's Sales      = invoice totals dated today - sales return totals dated today
- Today's Collection = posted customer collections dated today
- Today's Expenses   = posted expenses dated today + payroll paid today
- Today's Purchase   = goods receipt totals dated today - purchase return totals dated today
- Cash / Bank / MFS  = account balances by type (v_cash_position)
- Customer / Supplier Due = sum of positive balances (v_customer_due / v_supplier_due)
- Inventory Value    = sum(on_hand x avg_cost) (v_stock_valuation)
- Pending Orders     = sales orders confirmed / partially delivered: count and remaining value
- Estimated Profit (month to date) = net sales - net COGS + other income - expenses

"Today" and the month start are business dates in Asia/Dhaka. Document values are the
net (after discount) totals; reversed / pending / rejected vouchers don't count.
"""

from collections.abc import Iterable
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.dates import today
from app.core.db import utcnow
from app.modules.employees.models import PAID, PayrollRun
from app.modules.inventory.models import v_stock_valuation
from app.modules.master.models import Product
from app.modules.money.models import (
    BANK,
    CASH,
    MFS,
    POSTED,
    CustomerCollection,
    Expense,
    Income,
    v_cash_position,
)
from app.modules.parties.models import Customer, Supplier, v_customer_due, v_supplier_due
from app.modules.purchase.models import GoodsReceipt, PurchaseReturn
from app.modules.sales.models import (
    CONFIRMED,
    PARTIALLY_DELIVERED,
    Invoice,
    SalesOrder,
    SalesReturn,
    SalesReturnItem,
)

ZERO = Decimal("0.00")
Q2 = Decimal("0.01")
SERIES_DAYS = 7
TOP = 5

# section -> permissions it needs (all of them)
SECTIONS: dict[str, tuple[str, ...]] = {
    "today_sales": ("invoice.view",),
    "today_collection": ("collection.view",),
    "today_expenses": ("expense.view",),
    "today_purchase": ("goods_receipt.view",),
    "money": ("money_account.view",),
    "customer_due": ("customer.view",),
    "supplier_due": ("supplier.view",),
    # valued at cost: only for roles that also see purchase costs
    "inventory_value": ("stock.view", "goods_receipt.view"),
    "low_stock": ("stock.view",),
    "pending_orders": ("sales_order.view",),
    "profit": ("invoice.view", "expense.view", "income.view"),
}


def allowed_sections(permissions: Iterable[str]) -> list[str]:
    codes = set(permissions)
    return [name for name, needs in SECTIONS.items() if all(p in codes for p in needs)]


def _sum(db: Session, stmt: Select[Any]) -> Decimal:
    return Decimal(db.scalar(stmt) or 0).quantize(Q2)


def _total(column: Any, date_col: Any, start: date, end: date, *where: Any) -> Select[Any]:
    return select(func.coalesce(func.sum(column), 0)).where(
        date_col >= start, date_col <= end, *where
    )


# --- building blocks (date ranges are inclusive business dates) ------------------------


def net_sales(db: Session, start: date, end: date) -> Decimal:
    invoiced = _sum(db, _total(Invoice.total, Invoice.invoice_date, start, end))
    returned = _sum(db, _total(SalesReturn.total, SalesReturn.return_date, start, end))
    return invoiced - returned


def collections(db: Session, start: date, end: date) -> Decimal:
    return _sum(
        db,
        _total(
            CustomerCollection.amount,
            CustomerCollection.collection_date,
            start,
            end,
            CustomerCollection.status == POSTED,
        ),
    )


def expenses(db: Session, start: date, end: date) -> Decimal:
    """Posted expense vouchers + paid payroll runs (by payment date)."""
    vouchers = _sum(
        db, _total(Expense.amount, Expense.expense_date, start, end, Expense.status == POSTED)
    )
    payroll = _sum(
        db,
        _total(
            PayrollRun.total_net, PayrollRun.payment_date, start, end, PayrollRun.status == PAID
        ),
    )
    return vouchers + payroll


def other_income(db: Session, start: date, end: date) -> Decimal:
    return _sum(db, _total(Income.amount, Income.income_date, start, end, Income.status == POSTED))


def net_purchase(db: Session, start: date, end: date) -> Decimal:
    received = _sum(db, _total(GoodsReceipt.total, GoodsReceipt.receipt_date, start, end))
    returned = _sum(db, _total(PurchaseReturn.total, PurchaseReturn.return_date, start, end))
    return received - returned


def net_cogs(db: Session, start: date, end: date) -> Decimal:
    """COGS of invoices minus the cost of goods that came back (at their original COGS)."""
    sold = _sum(db, _total(Invoice.cogs_total, Invoice.invoice_date, start, end))
    returned_lines = db.execute(
        select(SalesReturnItem.qty, SalesReturnItem.unit_cost)
        .join(SalesReturn, SalesReturn.id == SalesReturnItem.return_id)
        .where(SalesReturn.return_date >= start, SalesReturn.return_date <= end)
    ).all()
    returned = sum(((qty * cost).quantize(Q2, ROUND_HALF_UP) for qty, cost in returned_lines), ZERO)
    return sold - returned


def estimated_profit(db: Session, start: date, end: date) -> Decimal:
    return (
        net_sales(db, start, end)
        - net_cogs(db, start, end)
        + other_income(db, start, end)
        - expenses(db, start, end)
    )


def cash_position(db: Session) -> dict[str, Decimal]:
    by_type = dict(
        db.execute(
            select(v_cash_position.c.account_type, func.sum(v_cash_position.c.balance)).group_by(
                v_cash_position.c.account_type
            )
        ).all()
    )
    return {t: Decimal(by_type.get(t) or 0).quantize(Q2) for t in (CASH, BANK, MFS)}


def _positive_due(db: Session, view: Any) -> Decimal:
    return _sum(db, select(func.coalesce(func.sum(view.c.due), 0)).where(view.c.due > 0))


def _top_due(db: Session, view: Any, id_col: Any, model: Any) -> list[dict[str, Any]]:
    rows = db.execute(
        select(id_col, model.code, view.c.name, view.c.due)
        .join(model, model.id == id_col)
        .where(view.c.due > 0)
        .order_by(view.c.due.desc(), id_col)
        .limit(TOP)
    ).all()
    return [{"id": i, "code": code, "name": name, "due": due} for i, code, name, due in rows]


def inventory_value(db: Session) -> Decimal:
    """sum(on_hand x avg_cost) over the view's rows, rounded once (not per row)."""
    v = v_stock_valuation
    exact = db.scalar(select(func.coalesce(func.sum(v.c.qty_on_hand * v.c.avg_cost), 0)))
    return Decimal(exact or 0).quantize(Q2, ROUND_HALF_UP)


def low_stock(db: Session) -> list[dict[str, Any]]:
    """Same rule as the stock screen's low-stock filter: reorder level set and on hand at
    or below it (per warehouse). Lowest cover first."""
    v = v_stock_valuation
    rows = db.execute(
        select(
            v.c.product_id,
            v.c.product_code,
            v.c.product_name,
            v.c.warehouse_name,
            v.c.qty_on_hand,
            Product.reorder_level,
        )
        .join(Product, Product.id == v.c.product_id)
        .where(
            Product.is_active.is_(True),
            Product.reorder_level > 0,
            v.c.qty_on_hand <= Product.reorder_level,
        )
        .order_by((v.c.qty_on_hand - Product.reorder_level).asc(), v.c.product_code)
        .limit(TOP)
    ).all()
    keys = (
        "product_id",
        "product_code",
        "product_name",
        "warehouse_name",
        "qty_on_hand",
        "reorder_level",
    )
    return [dict(zip(keys, r, strict=True)) for r in rows]


def pending_orders(db: Session) -> tuple[int, Decimal]:
    """Open sales orders and the value still to deliver: remaining qty x price, less the
    order's discount in the same proportion."""
    orders = list(
        db.scalars(
            select(SalesOrder).where(SalesOrder.status.in_((CONFIRMED, PARTIALLY_DELIVERED)))
        )
    )
    value = ZERO
    for so in orders:
        gross = sum(((i.qty_ordered - i.qty_delivered) * i.unit_price for i in so.items), ZERO)
        if so.subtotal > 0:
            gross = gross * so.total / so.subtotal
        value += gross.quantize(Q2, ROUND_HALF_UP)
    return len(orders), value


# --- summary ---------------------------------------------------------------------------


def summary(db: Session, permissions: Iterable[str]) -> dict[str, Any]:
    sections = allowed_sections(permissions)
    has = set(sections)
    day = today()
    month_start = day.replace(day=1)
    out: dict[str, Any] = {
        "as_of": day,
        "month_start": month_start,
        "generated_at": utcnow(),
        "sections": sections,
    }
    if "today_sales" in has:
        out["today_sales"] = net_sales(db, day, day)
    if "today_collection" in has:
        out["today_collection"] = collections(db, day, day)
    if "today_expenses" in has:
        out["today_expenses"] = expenses(db, day, day)
    if "today_purchase" in has:
        out["today_purchase"] = net_purchase(db, day, day)
    if "money" in has:
        position = cash_position(db)
        out |= {
            "cash_balance": position[CASH],
            "bank_balance": position[BANK],
            "mfs_balance": position[MFS],
        }
    if "customer_due" in has:
        out["customer_due"] = _positive_due(db, v_customer_due)
        out["top_customers"] = _top_due(db, v_customer_due, v_customer_due.c.customer_id, Customer)
    if "supplier_due" in has:
        out["supplier_due"] = _positive_due(db, v_supplier_due)
        out["top_suppliers"] = _top_due(db, v_supplier_due, v_supplier_due.c.supplier_id, Supplier)
    if "inventory_value" in has:
        out["inventory_value"] = inventory_value(db)
    if "low_stock" in has:
        out["low_stock"] = low_stock(db)
    if "pending_orders" in has:
        out["pending_orders_count"], out["pending_orders_value"] = pending_orders(db)
    if "profit" in has:
        out["estimated_profit_mtd"] = estimated_profit(db, month_start, day)
    if has & {"today_sales", "today_collection"}:
        points = []
        for offset in range(SERIES_DAYS - 1, -1, -1):
            d = day - timedelta(days=offset)
            point: dict[str, Any] = {"date": d}
            if "today_sales" in has:
                point["sales"] = net_sales(db, d, d)
            if "today_collection" in has:
                point["collection"] = collections(db, d, d)
            points.append(point)
        out["sales_vs_collection"] = points
    return out
