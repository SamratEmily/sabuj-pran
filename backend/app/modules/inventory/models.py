from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin

QTY = Numeric(18, 3)
COST = Numeric(18, 4)
ZERO_QTY = Decimal("0.000")

# Ledger transaction types
PURCHASE_IN = "PURCHASE_IN"
PURCHASE_RETURN_OUT = "PURCHASE_RETURN_OUT"
SALE_OUT = "SALE_OUT"
SALE_RETURN_IN = "SALE_RETURN_IN"
TRANSFER_OUT = "TRANSFER_OUT"
TRANSFER_IN = "TRANSFER_IN"
ADJUST_IN = "ADJUST_IN"
ADJUST_OUT = "ADJUST_OUT"
COUNT_IN = "COUNT_IN"
COUNT_OUT = "COUNT_OUT"
OPENING = "OPENING"

IN_TYPES = (PURCHASE_IN, SALE_RETURN_IN, TRANSFER_IN, ADJUST_IN, COUNT_IN, OPENING)
OUT_TYPES = (PURCHASE_RETURN_OUT, SALE_OUT, TRANSFER_OUT, ADJUST_OUT, COUNT_OUT)
TXN_TYPES = IN_TYPES + OUT_TYPES

# Document statuses
DRAFT = "draft"
PENDING_APPROVAL = "pending_approval"
POSTED = "posted"
CANCELLED = "cancelled"
REJECTED = "rejected"

INCREASE = "increase"
DECREASE = "decrease"


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class StockBalance(Base):
    """Current position per product per warehouse. Always changed under SELECT ... FOR UPDATE."""

    __tablename__ = "stock_balances"
    __table_args__ = (
        UniqueConstraint("product_id", "warehouse_id"),
        CheckConstraint(
            "qty_on_hand >= 0 AND qty_reserved >= 0 AND qty_reserved <= qty_on_hand "
            "AND avg_cost >= 0",
            name="non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), index=True)
    qty_on_hand: Mapped[Decimal] = mapped_column(QTY, default=ZERO_QTY)
    qty_reserved: Mapped[Decimal] = mapped_column(QTY, default=ZERO_QTY)
    avg_cost: Mapped[Decimal] = mapped_column(COST, default=Decimal("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class StockTransaction(Base):
    """Stock ledger. Append-only (UPDATE/DELETE blocked by triggers, migration 0006)."""

    __tablename__ = "stock_transactions"
    __table_args__ = (
        Index("ix_stock_transactions_product_wh_id", "product_id", "warehouse_id", "id"),
        Index("ix_stock_transactions_product_date", "product_id", "txn_date"),
        CheckConstraint(_in_list("txn_type", TXN_TYPES), name="txn_type"),
        CheckConstraint(
            "(qty_in > 0 AND qty_out = 0) OR (qty_out > 0 AND qty_in = 0)", name="one_side"
        ),
        CheckConstraint("balance_after >= 0 AND unit_cost >= 0", name="non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), index=True)
    txn_type: Mapped[str] = mapped_column(String(20))
    qty_in: Mapped[Decimal] = mapped_column(QTY, default=ZERO_QTY)
    qty_out: Mapped[Decimal] = mapped_column(QTY, default=ZERO_QTY)
    unit_cost: Mapped[Decimal] = mapped_column(COST)
    balance_after: Mapped[Decimal] = mapped_column(QTY)
    ref_type: Mapped[str] = mapped_column(String(30))
    ref_id: Mapped[int | None] = mapped_column(Integer)
    txn_date: Mapped[date] = mapped_column(Date)
    note: Mapped[str] = mapped_column(String(255), default="")
    # Set on a reversing row; unique so an entry can be reversed at most once.
    reversal_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_transactions.id"), unique=True
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class _DocumentMixin(TimestampMixin):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    status: Mapped[str] = mapped_column(String(20), default=DRAFT, index=True)
    note: Mapped[str] = mapped_column(String(500), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    posted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime)


class StockTransfer(_DocumentMixin, Base):
    __tablename__ = "stock_transfers"
    __table_args__ = (
        CheckConstraint("from_warehouse_id <> to_warehouse_id", name="different_warehouses"),
        CheckConstraint(_in_list("status", (DRAFT, POSTED, CANCELLED)), name="status"),
    )

    from_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    to_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    transfer_date: Mapped[date] = mapped_column(Date)

    items: Mapped[list["StockTransferItem"]] = relationship(
        order_by="StockTransferItem.id", cascade="all, delete-orphan"
    )


class StockTransferItem(Base):
    __tablename__ = "stock_transfer_items"
    __table_args__ = (CheckConstraint("qty > 0", name="qty_positive"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transfer_id: Mapped[int] = mapped_column(ForeignKey("stock_transfers.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    unit_cost: Mapped[Decimal | None] = mapped_column(COST)  # source avg, set when posted


class StockAdjustment(_DocumentMixin, Base):
    __tablename__ = "stock_adjustments"
    __table_args__ = (
        CheckConstraint(
            _in_list("status", (DRAFT, PENDING_APPROVAL, POSTED, CANCELLED, REJECTED)),
            name="status",
        ),
    )

    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    adjustment_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(255))

    items: Mapped[list["StockAdjustmentItem"]] = relationship(
        order_by="StockAdjustmentItem.id", cascade="all, delete-orphan"
    )


class StockAdjustmentItem(Base):
    __tablename__ = "stock_adjustment_items"
    __table_args__ = (
        CheckConstraint("qty > 0", name="qty_positive"),
        CheckConstraint(_in_list("direction", (INCREASE, DECREASE)), name="direction"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    adjustment_id: Mapped[int] = mapped_column(ForeignKey("stock_adjustments.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    direction: Mapped[str] = mapped_column(String(10))
    qty: Mapped[Decimal] = mapped_column(QTY)
    # Optional cost for increases on input; the cost actually used is stored when posted.
    unit_cost: Mapped[Decimal | None] = mapped_column(COST)
    note: Mapped[str] = mapped_column(String(255), default="")


class StockCount(_DocumentMixin, Base):
    __tablename__ = "stock_counts"
    __table_args__ = (
        CheckConstraint(_in_list("status", (DRAFT, POSTED, CANCELLED)), name="status"),
    )

    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    count_date: Mapped[date] = mapped_column(Date)

    items: Mapped[list["StockCountItem"]] = relationship(
        order_by="StockCountItem.id", cascade="all, delete-orphan"
    )


class StockCountItem(Base):
    __tablename__ = "stock_count_items"
    __table_args__ = (CheckConstraint("counted_qty >= 0", name="counted_non_negative"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    count_id: Mapped[int] = mapped_column(ForeignKey("stock_counts.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    system_qty: Mapped[Decimal] = mapped_column(QTY)  # snapshot when the count was created
    counted_qty: Mapped[Decimal] = mapped_column(QTY)
    variance: Mapped[Decimal] = mapped_column(QTY)  # counted - system (snapshot)
    unit_cost: Mapped[Decimal | None] = mapped_column(COST)  # cost used when posted


# SQL view (migration 0006): per product + warehouse value at average cost. Separate
# MetaData so Alembic never tries to create it as a table.
views_metadata = MetaData()
v_stock_valuation = Table(
    "v_stock_valuation",
    views_metadata,
    Column("product_id", Integer, primary_key=True),
    Column("product_code", String(20)),
    Column("product_name", String(150)),
    Column("warehouse_id", Integer, primary_key=True),
    Column("warehouse_name", String(100)),
    Column("qty_on_hand", Numeric(18, 3)),
    Column("avg_cost", Numeric(18, 4)),
    Column("value", Numeric(18, 2)),
)
