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

MONEY = Numeric(18, 2)
ZERO = Decimal("0.00")

CASH, BANK, MFS = "cash", "bank", "mfs"
ACCOUNT_TYPES = (CASH, BANK, MFS)
IN, OUT = "in", "out"

# Money ledger transaction types
OPENING = "OPENING"
COLLECTION = "COLLECTION"
SUPPLIER_PAYMENT = "SUPPLIER_PAYMENT"
EXPENSE = "EXPENSE"
INCOME = "INCOME"
TRANSFER_OUT = "TRANSFER_OUT"
TRANSFER_IN = "TRANSFER_IN"
PAYROLL = "PAYROLL"
REFUND = "REFUND"
TXN_TYPES = (
    OPENING,
    COLLECTION,
    SUPPLIER_PAYMENT,
    EXPENSE,
    INCOME,
    TRANSFER_OUT,
    TRANSFER_IN,
    PAYROLL,
    REFUND,
)

# Voucher statuses
DRAFT = "draft"
PENDING_APPROVAL = "pending_approval"
POSTED = "posted"
REVERSED = "reversed"
REJECTED = "rejected"
VOUCHER_STATUSES = (DRAFT, PENDING_APPROVAL, POSTED, REVERSED, REJECTED)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class MoneyAccount(TimestampMixin, Base):
    """Cash / bank / MFS account. `balance` is changed only under SELECT ... FOR UPDATE and
    always equals SUM(in) - SUM(out) of its ledger rows."""

    __tablename__ = "money_accounts"
    __table_args__ = (
        CheckConstraint(_in_list("account_type", ACCOUNT_TYPES), name="account_type"),
        CheckConstraint("balance >= 0", name="balance_non_negative"),
        CheckConstraint("opening_balance >= 0", name="opening_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    account_type: Mapped[str] = mapped_column(String(10), index=True)
    payment_method_id: Mapped[int | None] = mapped_column(ForeignKey("payment_methods.id"))
    account_number: Mapped[str] = mapped_column(String(50), default="")
    opening_balance: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)  # informational
    balance: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class MoneyTransaction(Base):
    """Money ledger. Append-only (UPDATE/DELETE blocked by triggers, migration 0008)."""

    __tablename__ = "money_transactions"
    __table_args__ = (
        Index("ix_money_transactions_account_id_id", "account_id", "id"),
        Index("ix_money_transactions_account_date", "account_id", "txn_date"),
        Index("ix_money_transactions_ref", "ref_type", "ref_id"),
        CheckConstraint(_in_list("direction", (IN, OUT)), name="direction"),
        CheckConstraint(_in_list("txn_type", TXN_TYPES), name="txn_type"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("balance_after >= 0", name="balance_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("money_accounts.id"))
    direction: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    txn_type: Mapped[str] = mapped_column(String(20))
    ref_type: Mapped[str] = mapped_column(String(30))
    ref_id: Mapped[int | None] = mapped_column(Integer)
    txn_date: Mapped[date] = mapped_column(Date)
    note: Mapped[str] = mapped_column(String(255), default="")
    balance_after: Mapped[Decimal] = mapped_column(MONEY)
    # Set on a reversing row; unique so a row is reversed at most once.
    reversal_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("money_transactions.id"), unique=True
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class _VoucherMixin(TimestampMixin):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("money_accounts.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    notes: Mapped[str] = mapped_column(String(1000), default="")
    status: Mapped[str] = mapped_column(String(20), default=DRAFT, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime)
    reversed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime)
    reversal_reason: Mapped[str] = mapped_column(String(255), default="")


def _voucher_checks() -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(_in_list("status", VOUCHER_STATUSES), name="status"),
    )


class CustomerCollection(_VoucherMixin, Base):
    __tablename__ = "customer_collections"
    __table_args__ = _voucher_checks()

    col_number: Mapped[str] = mapped_column(String(30), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    collection_date: Mapped[date] = mapped_column(Date, index=True)
    # Optional link: the invoice's paid_amount/status follow its collections.
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), index=True)
    reference_no: Mapped[str] = mapped_column(String(100), default="")


class SupplierPayment(_VoucherMixin, Base):
    __tablename__ = "supplier_payments"
    __table_args__ = _voucher_checks()

    pay_number: Mapped[str] = mapped_column(String(30), unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    payment_date: Mapped[date] = mapped_column(Date, index=True)
    reference_no: Mapped[str] = mapped_column(String(100), default="")


class Expense(_VoucherMixin, Base):
    __tablename__ = "expenses"
    __table_args__ = _voucher_checks()

    exp_number: Mapped[str] = mapped_column(String(30), unique=True)
    expense_category_id: Mapped[int] = mapped_column(
        ForeignKey("expense_categories.id"), index=True
    )
    expense_date: Mapped[date] = mapped_column(Date, index=True)
    paid_to: Mapped[str] = mapped_column(String(150), default="")


class Income(_VoucherMixin, Base):
    __tablename__ = "incomes"
    __table_args__ = _voucher_checks()

    inc_number: Mapped[str] = mapped_column(String(30), unique=True)
    income_category_id: Mapped[int] = mapped_column(ForeignKey("income_categories.id"), index=True)
    income_date: Mapped[date] = mapped_column(Date, index=True)


class MoneyTransfer(TimestampMixin, Base):
    __tablename__ = "money_transfers"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("from_account_id <> to_account_id", name="different_accounts"),
        CheckConstraint(_in_list("status", (POSTED, REVERSED)), name="status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mtr_number: Mapped[str] = mapped_column(String(30), unique=True)
    from_account_id: Mapped[int] = mapped_column(ForeignKey("money_accounts.id"), index=True)
    to_account_id: Mapped[int] = mapped_column(ForeignKey("money_accounts.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    transfer_date: Mapped[date] = mapped_column(Date, index=True)
    notes: Mapped[str] = mapped_column(String(1000), default="")
    status: Mapped[str] = mapped_column(String(20), default=POSTED)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reversed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime)
    reversal_reason: Mapped[str] = mapped_column(String(255), default="")


# View (migration 0008): per-account balance from the ledger, with its type.
views_metadata = MetaData()
v_cash_position = Table(
    "v_cash_position",
    views_metadata,
    Column("account_id", Integer, primary_key=True),
    Column("name", String(100)),
    Column("account_type", String(10)),
    Column("is_active", Boolean),
    Column("balance", Numeric(18, 2)),
)
