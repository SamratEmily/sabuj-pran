from datetime import date

from pydantic import BaseModel

from app.core.schemas import Money, Qty, UtcDateTime


class PartyDue(BaseModel):
    id: int
    code: str
    name: str
    due: Money


class LowStock(BaseModel):
    product_id: int
    product_code: str
    product_name: str
    warehouse_name: str
    qty_on_hand: Qty
    reorder_level: Qty


class SeriesPoint(BaseModel):
    date: date
    sales: Money | None = None  # null when the user can't see sales
    collection: Money | None = None  # null when the user can't see collections


class DashboardOut(BaseModel):
    """Every metric is optional: only the sections the user's permissions allow are
    returned (the response omits the rest)."""

    as_of: date
    month_start: date
    generated_at: UtcDateTime
    sections: list[str]
    today_sales: Money | None = None
    today_collection: Money | None = None
    today_expenses: Money | None = None
    today_purchase: Money | None = None
    cash_balance: Money | None = None
    bank_balance: Money | None = None
    mfs_balance: Money | None = None
    customer_due: Money | None = None
    supplier_due: Money | None = None
    inventory_value: Money | None = None
    pending_orders_count: int | None = None
    pending_orders_value: Money | None = None
    estimated_profit_mtd: Money | None = None
    top_customers: list[PartyDue] | None = None
    top_suppliers: list[PartyDue] | None = None
    low_stock: list[LowStock] | None = None
    sales_vs_collection: list[SeriesPoint] | None = None
