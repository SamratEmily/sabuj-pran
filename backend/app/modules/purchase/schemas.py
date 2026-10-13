from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.core.schemas import Money, Qty, UnitCost, UtcDateTime

PositiveQty = Annotated[Qty, Field(gt=Decimal("0"))]
Cost = Annotated[UnitCost, Field(ge=Decimal("0"))]
Amount = Annotated[Money, Field(ge=Decimal("0"))]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
PoStatus = Literal[
    "draft",
    "pending_approval",
    "approved",
    "partially_received",
    "received",
    "cancelled",
    "rejected",
]


# --- input -----------------------------------------------------------------------------


class PoItemIn(BaseModel):
    product_id: int
    qty: PositiveQty
    unit_cost: Cost


class PoIn(BaseModel):
    supplier_id: int
    warehouse_id: int
    order_date: date | None = None  # default today
    expected_date: date | None = None
    discount: Amount = Decimal("0")
    notes: Notes = ""
    items: list[PoItemIn] = Field(min_length=1, max_length=500)


class ReceiveItemIn(BaseModel):
    po_item_id: int
    qty: PositiveQty
    unit_cost: Cost | None = None  # default: the PO line cost


class ReceiveIn(BaseModel):
    receipt_date: date | None = None
    notes: Notes = ""
    items: list[ReceiveItemIn] = Field(min_length=1, max_length=500)


class DirectPurchaseIn(PoIn):
    """A purchase received on the spot: creates a received PO + its goods receipt."""


class ReturnItemIn(BaseModel):
    grn_item_id: int
    qty: PositiveQty


class ReturnIn(BaseModel):
    return_date: date | None = None
    notes: Notes = ""
    items: list[ReturnItemIn] = Field(min_length=1, max_length=500)


# --- output ----------------------------------------------------------------------------


class _Line(BaseModel):
    id: int
    product_id: int
    product_code: str
    product_name: str
    unit_code: str


class PoItemOut(_Line):
    qty: Qty
    unit_cost: UnitCost
    line_total: Money
    received_qty: Qty
    remaining_qty: Qty


class ReturnItemOut(_Line):
    grn_item_id: int
    qty: Qty
    unit_cost: UnitCost
    line_total: Money


class ReturnOut(BaseModel):
    id: int
    prn_number: str
    goods_receipt_id: int
    grn_number: str
    po_id: int | None
    po_number: str | None
    supplier_id: int
    supplier_name: str
    warehouse_id: int
    warehouse_name: str
    return_date: date
    subtotal: Money
    discount: Money
    total: Money
    notes: str
    created_by_name: str
    created_at: UtcDateTime
    items: list[ReturnItemOut]


class ReceiptItemOut(_Line):
    po_item_id: int | None
    qty: Qty
    unit_cost: UnitCost
    line_total: Money
    returned_qty: Qty
    returnable_qty: Qty


class ReceiptOut(BaseModel):
    id: int
    grn_number: str
    po_id: int | None
    po_number: str | None
    supplier_id: int
    supplier_name: str
    warehouse_id: int
    warehouse_name: str
    receipt_date: date
    subtotal: Money
    discount: Money
    total: Money
    is_direct: bool
    notes: str
    created_by_name: str
    created_at: UtcDateTime
    items: list[ReceiptItemOut]
    returns: list[ReturnOut]


class PoOut(BaseModel):
    id: int
    po_number: str
    supplier_id: int
    supplier_code: str
    supplier_name: str
    warehouse_id: int
    warehouse_name: str
    order_date: date
    expected_date: date | None
    status: PoStatus
    subtotal: Money
    discount: Money
    total: Money
    notes: str
    created_by_name: str
    approved_by_name: str | None
    approved_at: UtcDateTime | None
    created_at: UtcDateTime
    items: list[PoItemOut]


class PoDetailOut(PoOut):
    receipts: list[ReceiptOut]
    supplier_due: Money  # supplier's current payable balance (all documents)
