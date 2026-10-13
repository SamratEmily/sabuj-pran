from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.core.pagination import Page
from app.core.schemas import Money, Qty, UnitCost, UtcDateTime

PositiveQty = Annotated[Qty, Field(gt=Decimal("0"))]
NonNegativeQty = Annotated[Qty, Field(ge=Decimal("0"))]
NonNegativeCost = Annotated[UnitCost, Field(ge=Decimal("0"))]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Status = Literal["draft", "pending_approval", "posted", "cancelled", "rejected"]


# --- input -----------------------------------------------------------------------------


class TransferItemIn(BaseModel):
    product_id: int
    qty: PositiveQty


class TransferIn(BaseModel):
    from_warehouse_id: int
    to_warehouse_id: int
    transfer_date: date | None = None  # default today
    note: Note = ""
    items: list[TransferItemIn] = Field(min_length=1, max_length=500)


class AdjustmentItemIn(BaseModel):
    product_id: int
    direction: Literal["increase", "decrease"]
    qty: PositiveQty
    # Increases only; default = current average, else the product's purchase price.
    unit_cost: NonNegativeCost | None = None
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] = ""


class AdjustmentIn(BaseModel):
    warehouse_id: int
    adjustment_date: date | None = None
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    note: Note = ""
    items: list[AdjustmentItemIn] = Field(min_length=1, max_length=500)


class CountItemIn(BaseModel):
    product_id: int
    counted_qty: NonNegativeQty


class CountIn(BaseModel):
    warehouse_id: int
    count_date: date | None = None
    note: Note = ""
    items: list[CountItemIn] = Field(min_length=1, max_length=2000)


# --- output: documents -----------------------------------------------------------------


class _DocItemOut(BaseModel):
    id: int
    product_id: int
    product_code: str
    product_name: str
    unit_code: str
    unit_cost: UnitCost | None


class TransferItemOut(_DocItemOut):
    qty: Qty


class AdjustmentItemOut(_DocItemOut):
    direction: Literal["increase", "decrease"]
    qty: Qty
    note: str


class CountItemOut(_DocItemOut):
    system_qty: Qty
    counted_qty: Qty
    variance: Qty
    # Live on-hand while the count is a draft (to spot movement since the snapshot).
    current_qty: Qty | None


class _DocOut(BaseModel):
    id: int
    number: str
    status: Status
    note: str
    created_by_name: str
    posted_by_name: str | None
    posted_at: UtcDateTime | None
    created_at: UtcDateTime


class TransferOut(_DocOut):
    from_warehouse_id: int
    from_warehouse_name: str
    to_warehouse_id: int
    to_warehouse_name: str
    transfer_date: date
    items: list[TransferItemOut]


class AdjustmentOut(_DocOut):
    warehouse_id: int
    warehouse_name: str
    adjustment_date: date
    reason: str
    items: list[AdjustmentItemOut]


class CountOut(_DocOut):
    warehouse_id: int
    warehouse_name: str
    count_date: date
    items: list[CountItemOut]


class CountPostOut(CountOut):
    # Products whose on-hand changed between the snapshot and posting (variance still applied).
    moved_since_snapshot: list[int]


# --- output: stock & ledger ------------------------------------------------------------


class StockRow(BaseModel):
    product_id: int
    product_code: str
    product_name: str
    product_type: str
    category_name: str
    unit_code: str
    warehouse_id: int
    warehouse_name: str
    qty_on_hand: Qty
    qty_reserved: Qty
    qty_available: Qty
    avg_cost: UnitCost
    value: Money
    reorder_level: Qty
    is_low: bool


class StockPage(Page[StockRow]):
    total_value: Money


class LedgerRow(BaseModel):
    id: int
    txn_date: date
    txn_type: str
    warehouse_id: int
    warehouse_name: str
    qty_in: Qty
    qty_out: Qty
    unit_cost: UnitCost
    balance_after: Qty
    running_balance: Qty
    ref_type: str
    ref_id: int | None
    note: str
    reversal_of_id: int | None
    created_by_name: str | None
    created_at: UtcDateTime


class LedgerPage(Page[LedgerRow]):
    product_id: int
    product_code: str
    product_name: str
    opening_balance: Qty
    closing_balance: Qty  # opening + all movements in the range (not just this page)
