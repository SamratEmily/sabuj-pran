from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin

PRODUCT_TYPES = ("raw_material", "finished_good", "trading")
PAYMENT_METHOD_TYPES = ("cash", "bank", "mfs", "online")


class Category(TimestampMixin, Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Unit(TimestampMixin, Base):
    __tablename__ = "units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    short_code: Mapped[str] = mapped_column(String(10), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(
            "product_type IN ('raw_material', 'finished_good', 'trading')", name="product_type"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), index=True)
    product_type: Mapped[str] = mapped_column(String(20), index=True)
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    reorder_level: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=Decimal("0"))
    description: Mapped[str] = mapped_column(String(500), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    category: Mapped[Category] = relationship()
    unit: Mapped[Unit] = relationship()


class ProductPrice(Base):
    """Selling price history. Append-only: a new row supersedes older ones from its date."""

    __tablename__ = "product_prices"
    __table_args__ = (Index("ix_product_prices_product_effective", "product_id", "effective_from"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    effective_from: Mapped[date] = mapped_column(Date)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Warehouse(TimestampMixin, Base):
    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    address: Mapped[str] = mapped_column(String(500), default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ExpenseCategory(TimestampMixin, Base):
    __tablename__ = "expense_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class IncomeCategory(TimestampMixin, Base):
    __tablename__ = "income_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PaymentMethod(TimestampMixin, Base):
    __tablename__ = "payment_methods"
    __table_args__ = (
        CheckConstraint("method_type IN ('cash', 'bank', 'mfs', 'online')", name="method_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    method_type: Mapped[str] = mapped_column(String(10))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
