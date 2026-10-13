from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
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

DRAFT = "draft"
PENDING_APPROVAL = "pending_approval"
APPROVED = "approved"
PARTIALLY_RECEIVED = "partially_received"
RECEIVED = "received"
CANCELLED = "cancelled"
REJECTED = "rejected"
PO_STATUSES = (
    DRAFT,
    PENDING_APPROVAL,
    APPROVED,
    PARTIALLY_RECEIVED,
    RECEIVED,
    CANCELLED,
    REJECTED,
)


class PurchaseOrder(TimestampMixin, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(repr(s) for s in PO_STATUSES) + ")", name="status"
        ),
        CheckConstraint("discount >= 0 AND discount <= subtotal", name="discount_range"),
        CheckConstraint("total = subtotal - discount", name="total"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    po_number: Mapped[str] = mapped_column(String(30), unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    order_date: Mapped[date] = mapped_column(Date, index=True)
    expected_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default=DRAFT, index=True)
    subtotal: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    # Bill-only discount: reduces what we owe the supplier, not the stock cost.
    discount: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    total: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    notes: Mapped[str] = mapped_column(String(1000), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)

    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        order_by="PurchaseOrderItem.id", cascade="all, delete-orphan"
    )


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"
    __table_args__ = (
        CheckConstraint("qty > 0", name="qty_positive"),
        CheckConstraint("received_qty >= 0 AND received_qty <= qty", name="received_range"),
        CheckConstraint("unit_cost >= 0", name="cost_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    unit_cost: Mapped[Decimal] = mapped_column(COST)
    line_total: Mapped[Decimal] = mapped_column(MONEY)
    received_qty: Mapped[Decimal] = mapped_column(QTY, default=ZERO)


class GoodsReceipt(Base):
    __tablename__ = "goods_receipts"
    __table_args__ = (
        CheckConstraint("discount >= 0 AND discount <= subtotal", name="discount_range"),
        CheckConstraint("total = subtotal - discount", name="total"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    grn_number: Mapped[str] = mapped_column(String(30), unique=True)
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    receipt_date: Mapped[date] = mapped_column(Date, index=True)
    subtotal: Mapped[Decimal] = mapped_column(MONEY)  # gross at received cost
    discount: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)  # share of the PO discount
    total: Mapped[Decimal] = mapped_column(MONEY)  # net = supplier ledger credit
    is_direct: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(String(1000), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    items: Mapped[list["GoodsReceiptItem"]] = relationship(
        order_by="GoodsReceiptItem.id", cascade="all, delete-orphan"
    )


class GoodsReceiptItem(Base):
    __tablename__ = "goods_receipt_items"
    __table_args__ = (
        CheckConstraint("qty > 0", name="qty_positive"),
        CheckConstraint("returned_qty >= 0 AND returned_qty <= qty", name="returned_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    grn_id: Mapped[int] = mapped_column(ForeignKey("goods_receipts.id"), index=True)
    po_item_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_order_items.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    unit_cost: Mapped[Decimal] = mapped_column(COST)  # actual received cost (stock IN cost)
    line_total: Mapped[Decimal] = mapped_column(MONEY)
    returned_qty: Mapped[Decimal] = mapped_column(QTY, default=ZERO)


class PurchaseReturn(Base):
    __tablename__ = "purchase_returns"
    __table_args__ = (CheckConstraint("total = subtotal - discount", name="total"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prn_number: Mapped[str] = mapped_column(String(30), unique=True)
    goods_receipt_id: Mapped[int] = mapped_column(ForeignKey("goods_receipts.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    return_date: Mapped[date] = mapped_column(Date, index=True)
    subtotal: Mapped[Decimal] = mapped_column(MONEY)  # gross at receipt cost
    discount: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)  # receipt's discount share
    total: Mapped[Decimal] = mapped_column(MONEY)  # net = supplier ledger debit
    notes: Mapped[str] = mapped_column(String(1000), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    items: Mapped[list["PurchaseReturnItem"]] = relationship(
        order_by="PurchaseReturnItem.id", cascade="all, delete-orphan"
    )


class PurchaseReturnItem(Base):
    __tablename__ = "purchase_return_items"
    __table_args__ = (CheckConstraint("qty > 0", name="qty_positive"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    return_id: Mapped[int] = mapped_column(ForeignKey("purchase_returns.id"), index=True)
    grn_item_id: Mapped[int] = mapped_column(ForeignKey("goods_receipt_items.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    unit_cost: Mapped[Decimal] = mapped_column(COST)
    line_total: Mapped[Decimal] = mapped_column(MONEY)
