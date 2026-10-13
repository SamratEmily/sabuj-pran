from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin

CUSTOMER = "customer"
SUPPLIER = "supplier"
PARTY_TYPES = (CUSTOMER, SUPPLIER)


class PartyMixin(TimestampMixin):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(150), index=True)
    contact_person: Mapped[str] = mapped_column(String(100), default="")
    mobile: Mapped[str] = mapped_column(String(20), default="", index=True)
    email: Mapped[str] = mapped_column(String(150), default="")
    address: Mapped[str] = mapped_column(String(500), default="")
    # Informational copy of the opening balance; the ledger's OPENING entries are the truth.
    opening_due: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    notes: Mapped[str] = mapped_column(String(1000), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Customer(PartyMixin, Base):
    __tablename__ = "customers"


class Supplier(PartyMixin, Base):
    __tablename__ = "suppliers"


class PartyLedger(Base):
    """Append-only. UPDATE/DELETE are also blocked by database triggers (migration 0005).

    Customer due = SUM(debit) - SUM(credit); supplier due = SUM(credit) - SUM(debit).
    """

    __tablename__ = "party_ledger"
    __table_args__ = (
        Index("ix_party_ledger_party_date", "party_type", "party_id", "entry_date"),
        CheckConstraint("party_type IN ('customer', 'supplier')", name="party_type"),
        CheckConstraint(
            "(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)", name="one_side"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    party_type: Mapped[str] = mapped_column(String(10))
    party_id: Mapped[int] = mapped_column(Integer)
    entry_date: Mapped[date] = mapped_column(Date)
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    ref_type: Mapped[str] = mapped_column(String(30))
    ref_id: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(255), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# SQL views (created in migration 0005). Separate MetaData so Alembic never tries to create
# them as tables.
views_metadata = MetaData()
v_customer_due = Table(
    "v_customer_due",
    views_metadata,
    Column("customer_id", Integer, primary_key=True),
    Column("name", String(150)),
    Column("due", Numeric(18, 2)),
)
v_supplier_due = Table(
    "v_supplier_due",
    views_metadata,
    Column("supplier_id", Integer, primary_key=True),
    Column("name", String(150)),
    Column("due", Numeric(18, 2)),
)
