from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.core.schemas import Money, Qty, UnitCost, UtcDateTime

PositiveQty = Annotated[Qty, Field(gt=Decimal("0"))]
NonNegativeQty = Annotated[Qty, Field(ge=Decimal("0"))]
Price = Annotated[Money, Field(ge=Decimal("0"))]
Amount = Annotated[Money, Field(ge=Decimal("0"))]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
QuotationStatus = Literal["draft", "sent", "accepted", "rejected", "converted"]
SoStatus = Literal["draft", "confirmed", "partially_delivered", "delivered", "cancelled"]
InvoiceStatus = Literal["unpaid", "partial", "paid"]


# --- input -----------------------------------------------------------------------------


class LineIn(BaseModel):
    product_id: int
    qty: PositiveQty
    unit_price: Price


class QuotationIn(BaseModel):
    customer_id: int
    quote_date: date | None = None  # default today
    valid_until: date | None = None
    discount: Amount = Decimal("0")
    notes: Notes = ""
    items: list[LineIn] = Field(min_length=1, max_length=500)


class ConvertIn(BaseModel):
    warehouse_id: int | None = None  # default: the default warehouse


class SoIn(BaseModel):
    customer_id: int
    warehouse_id: int
    order_date: date | None = None  # default today
    delivery_date: date | None = None
    discount: Amount = Decimal("0")
    notes: Notes = ""
    items: list[LineIn] = Field(min_length=1, max_length=500)


class ProducedIn(BaseModel):
    qty_produced: NonNegativeQty


class ReserveIn(BaseModel):
    warehouse_id: int | None = None  # default: the order's warehouse


class DeliverItemIn(BaseModel):
    so_item_id: int
    qty: PositiveQty


class DeliverIn(BaseModel):
    delivery_date: date | None = None
    create_invoice: bool = True
    notes: Notes = ""
    items: list[DeliverItemIn] = Field(min_length=1, max_length=500)


class ReturnItemIn(BaseModel):
    invoice_item_id: int
    qty: PositiveQty


class SalesReturnIn(BaseModel):
    return_date: date | None = None
    refund_amount: Amount = Decimal("0")
    refund_account_id: int | None = None
    notes: Notes = ""
    items: list[ReturnItemIn] = Field(min_length=1, max_length=500)


# --- output ----------------------------------------------------------------------------


class _Line(BaseModel):
    id: int
    product_id: int
    product_code: str
    product_name: str
    unit_code: str


class _Customer(BaseModel):
    customer_id: int
    customer_code: str
    customer_name: str


class QuotationItemOut(_Line):
    qty: Qty
    unit_price: Money
    line_total: Money


class QuotationOut(_Customer):
    id: int
    qt_number: str
    quote_date: date
    valid_until: date | None
    status: QuotationStatus
    subtotal: Money
    discount: Money
    total: Money
    notes: str
    converted_order_id: int | None
    converted_order_number: str | None
    created_by_name: str
    created_at: UtcDateTime
    items: list[QuotationItemOut]


class QuotationDetailOut(QuotationOut):
    customer_due: Money


class SoItemOut(_Line):
    qty_ordered: Qty
    unit_price: Money
    line_total: Money
    qty_reserved: Qty
    qty_produced: Qty
    qty_delivered: Qty
    qty_remaining: Qty
    qty_available: Qty | None = None  # free stock in the order's warehouse (detail only)


class SoOut(_Customer):
    id: int
    so_number: str
    quotation_id: int | None
    quotation_number: str | None
    warehouse_id: int
    warehouse_name: str
    order_date: date
    delivery_date: date | None
    status: SoStatus
    subtotal: Money
    discount: Money
    total: Money
    notes: str
    created_by_name: str
    confirmed_by_name: str | None
    confirmed_at: UtcDateTime | None
    created_at: UtcDateTime
    items: list[SoItemOut]


class DeliveryItemOut(_Line):
    so_item_id: int
    qty: Qty
    unit_price: Money
    unit_cost_cogs: UnitCost


class DeliveryOut(_Customer):
    id: int
    dlv_number: str
    sales_order_id: int
    so_number: str
    warehouse_id: int
    warehouse_name: str
    delivery_date: date
    invoice_id: int | None
    inv_number: str | None
    notes: str
    created_by_name: str
    created_at: UtcDateTime
    items: list[DeliveryItemOut]


class InvoiceItemOut(_Line):
    delivery_item_id: int
    qty: Qty
    unit_price: Money
    unit_cost: UnitCost
    line_total: Money
    qty_returned: Qty
    qty_returnable: Qty


class InvoiceOut(_Customer):
    id: int
    inv_number: str
    sales_order_id: int
    so_number: str
    delivery_id: int
    dlv_number: str
    warehouse_id: int
    warehouse_name: str
    invoice_date: date
    subtotal: Money
    discount: Money
    total: Money
    paid_amount: Money
    returned_amount: Money
    refunded_amount: Money
    outstanding: Money
    status: InvoiceStatus
    cogs_total: Money
    created_by_name: str
    created_at: UtcDateTime
    items: list[InvoiceItemOut]


class SoDetailOut(SoOut):
    customer_due: Money
    deliveries: list[DeliveryOut]
    invoices: list[InvoiceOut]


class ReserveLineOut(BaseModel):
    so_item_id: int
    product_code: str
    product_name: str
    wanted: Qty  # remaining - already reserved, before this call
    reserved_now: Qty
    reserved_total: Qty
    short: Qty  # wanted - reserved_now


class ReserveOut(BaseModel):
    order: SoDetailOut
    lines: list[ReserveLineOut]


class ReturnItemOut(_Line):
    invoice_item_id: int
    qty: Qty
    unit_price: Money
    unit_cost: UnitCost
    line_total: Money


class SalesReturnOut(_Customer):
    id: int
    srn_number: str
    invoice_id: int
    inv_number: str
    warehouse_id: int
    warehouse_name: str
    return_date: date
    subtotal: Money
    discount: Money
    total: Money
    refund_amount: Money
    refund_account_id: int | None
    refund_account_name: str | None
    notes: str
    created_by_name: str
    created_at: UtcDateTime
    items: list[ReturnItemOut]


class InvoiceCollectionOut(BaseModel):
    id: int
    number: str
    collection_date: date
    amount: Money
    status: str
    account_name: str


class CompanyOut(BaseModel):
    company_name: str
    address: str
    phone: str
    email: str
    currency_symbol: str
    invoice_footer_note: str
    logo_url: str


class InvoiceDetailOut(InvoiceOut):
    customer_due: Money
    customer_mobile: str
    customer_address: str
    returns: list[SalesReturnOut]
    collections: list[InvoiceCollectionOut]
    company: CompanyOut
