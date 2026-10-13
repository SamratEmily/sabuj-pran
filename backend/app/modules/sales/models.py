from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin

MONEY = Numeric(18, 2)
QTY = Numeric(18, 3)
COST = Numeric(18, 4)
ZERO = Decimal("0")

# quotation statuses
DRAFT = "draft"
SENT = "sent"
ACCEPTED = "accepted"
REJECTED = "rejected"
CONVERTED = "converted"
QUOTATION_STATUSES = (DRAFT, SENT, ACCEPTED, REJECTED, CONVERTED)

# sales order statuses
CONFIRMED = "confirmed"
PARTIALLY_DELIVERED = "partially_delivered"
DELIVERED = "delivered"
CANCELLED = "cancelled"
SO_STATUSES = (DRAFT, CONFIRMED, PARTIALLY_DELIVERED, DELIVERED, CANCELLED)

# invoice statuses
UNPAID = "unpaid"
PARTIAL = "partial"
PAID = "paid"
INVOICE_STATUSES = (UNPAID, PARTIAL, PAID)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(repr(v) for v in values) + ")"


def _totals_checks() -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint("discount >= 0 AND discount <= subtotal", name="discount_range"),
        CheckConstraint("total = subtotal - discount", name="total"),
    )


class Quotation(TimestampMixin, Base):
    __tablename__ = "quotations"
    __table_args__ = (
        CheckConstraint(_in_list("status", QUOTATION_STATUSES), name="status"),
        *_totals_checks(),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    qt_number: Mapped[str] = mapped_column(String(30), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    quote_date: Mapped[date] = mapped_column(Date, index=True)
    valid_until: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default=DRAFT, index=True)
    subtotal: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    discount: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    total: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    notes: Mapped[str] = mapped_column(String(1000), default="")
    converted_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales_orders.id", use_alter=True)
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))

    items: Mapped[list["QuotationItem"]] = relationship(
        order_by="QuotationItem.id", cascade="all, delete-orphan"
    )


class QuotationItem(Base):
    __tablename__ = "quotation_items"
    __table_args__ = (
        CheckConstraint("qty > 0", name="qty_positive"),
        CheckConstraint("unit_price >= 0", name="price_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quotation_id: Mapped[int] = mapped_column(ForeignKey("quotations.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    line_total: Mapped[Decimal] = mapped_column(MONEY)


class SalesOrder(TimestampMixin, Base):
    __tablename__ = "sales_orders"
    __table_args__ = (
        CheckConstraint(_in_list("status", SO_STATUSES), name="status"),
        *_totals_checks(),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    so_number: Mapped[str] = mapped_column(String(30), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    quotation_id: Mapped[int | None] = mapped_column(ForeignKey("quotations.id"))
    # All reservations and deliveries of the order use this warehouse.
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    order_date: Mapped[date] = mapped_column(Date, index=True)
    delivery_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default=DRAFT, index=True)
    subtotal: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    discount: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    total: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    notes: Mapped[str] = mapped_column(String(1000), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)

    items: Mapped[list["SalesOrderItem"]] = relationship(
        order_by="SalesOrderItem.id", cascade="all, delete-orphan"
    )


class SalesOrderItem(Base):
    __tablename__ = "sales_order_items"
    __table_args__ = (
        CheckConstraint("qty_ordered > 0", name="qty_positive"),
        CheckConstraint("unit_price >= 0", name="price_non_negative"),
        CheckConstraint(
            "qty_delivered >= 0 AND qty_delivered <= qty_ordered", name="delivered_range"
        ),
        CheckConstraint(
            "qty_reserved >= 0 AND qty_reserved <= qty_ordered - qty_delivered",
            name="reserved_range",
        ),
        CheckConstraint("qty_produced >= 0", name="produced_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    so_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty_ordered: Mapped[Decimal] = mapped_column(QTY)
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    line_total: Mapped[Decimal] = mapped_column(MONEY)
    qty_reserved: Mapped[Decimal] = mapped_column(QTY, default=ZERO)
    qty_produced: Mapped[Decimal] = mapped_column(QTY, default=ZERO)  # manual, informational
    qty_delivered: Mapped[Decimal] = mapped_column(QTY, default=ZERO)


class Delivery(Base):
    __tablename__ = "deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dlv_number: Mapped[str] = mapped_column(String(30), unique=True)
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    delivery_date: Mapped[date] = mapped_column(Date, index=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id", use_alter=True))
    notes: Mapped[str] = mapped_column(String(1000), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    items: Mapped[list["DeliveryItem"]] = relationship(
        order_by="DeliveryItem.id", cascade="all, delete-orphan"
    )


class DeliveryItem(Base):
    __tablename__ = "delivery_items"
    __table_args__ = (CheckConstraint("qty > 0", name="qty_positive"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id"), index=True)
    so_item_id: Mapped[int] = mapped_column(ForeignKey("sales_order_items.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    unit_cost_cogs: Mapped[Decimal] = mapped_column(COST)  # avg cost at delivery time
    unit_price: Mapped[Decimal] = mapped_column(MONEY)


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint(_in_list("status", INVOICE_STATUSES), name="status"),
        *_totals_checks(),
        CheckConstraint("paid_amount >= 0", name="paid_non_negative"),
        CheckConstraint("returned_amount >= 0", name="returned_non_negative"),
        CheckConstraint("refunded_amount >= 0", name="refunded_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inv_number: Mapped[str] = mapped_column(String(30), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"), index=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id"), unique=True)
    invoice_date: Mapped[date] = mapped_column(Date, index=True)
    subtotal: Mapped[Decimal] = mapped_column(MONEY)
    discount: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)  # share of the SO discount
    total: Mapped[Decimal] = mapped_column(MONEY)  # customer ledger debit
    paid_amount: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)  # linked collections
    returned_amount: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)  # net sales returns
    refunded_amount: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)  # refunds paid out
    status: Mapped[str] = mapped_column(String(20), default=UNPAID, index=True)
    cogs_total: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    items: Mapped[list["InvoiceItem"]] = relationship(
        order_by="InvoiceItem.id", cascade="all, delete-orphan"
    )

    @property
    def outstanding(self) -> Decimal:
        return self.total - self.returned_amount + self.refunded_amount - self.paid_amount


class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    __table_args__ = (
        CheckConstraint("qty > 0", name="qty_positive"),
        CheckConstraint("qty_returned >= 0 AND qty_returned <= qty", name="returned_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    delivery_item_id: Mapped[int] = mapped_column(ForeignKey("delivery_items.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    unit_cost: Mapped[Decimal] = mapped_column(COST)  # COGS of the delivery line
    line_total: Mapped[Decimal] = mapped_column(MONEY)
    qty_returned: Mapped[Decimal] = mapped_column(QTY, default=ZERO)


class SalesReturn(Base):
    __tablename__ = "sales_returns"
    __table_args__ = (
        *_totals_checks(),
        CheckConstraint("refund_amount >= 0 AND refund_amount <= total", name="refund_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    srn_number: Mapped[str] = mapped_column(String(30), unique=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    return_date: Mapped[date] = mapped_column(Date, index=True)
    subtotal: Mapped[Decimal] = mapped_column(MONEY)
    discount: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)  # share of invoice discount
    total: Mapped[Decimal] = mapped_column(MONEY)  # customer ledger credit
    refund_amount: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    refund_account_id: Mapped[int | None] = mapped_column(ForeignKey("money_accounts.id"))
    notes: Mapped[str] = mapped_column(String(1000), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    items: Mapped[list["SalesReturnItem"]] = relationship(
        order_by="SalesReturnItem.id", cascade="all, delete-orphan"
    )


class SalesReturnItem(Base):
    __tablename__ = "sales_return_items"
    __table_args__ = (CheckConstraint("qty > 0", name="qty_positive"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    return_id: Mapped[int] = mapped_column(ForeignKey("sales_returns.id"), index=True)
    invoice_item_id: Mapped[int] = mapped_column(ForeignKey("invoice_items.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    unit_cost: Mapped[Decimal] = mapped_column(COST)  # original COGS (stock comes back at this)
    line_total: Mapped[Decimal] = mapped_column(MONEY)
