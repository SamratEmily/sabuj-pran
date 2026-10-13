from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin

PURCHASE_ORDER = "PURCHASE_ORDER"
EXPENSE = "EXPENSE"
SUPPLIER_PAYMENT = "SUPPLIER_PAYMENT"
STOCK_ADJUSTMENT = "STOCK_ADJUSTMENT"
DOCUMENT_TYPES = (PURCHASE_ORDER, EXPENSE, SUPPLIER_PAYMENT, STOCK_ADJUSTMENT)

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
APPROVAL_STATUSES = (PENDING, APPROVED, REJECTED)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(repr(v) for v in values) + ")"


class ApprovalRule(TimestampMixin, Base):
    __tablename__ = "approval_rules"
    __table_args__ = (
        CheckConstraint(_in_list("document_type", DOCUMENT_TYPES), name="document_type"),
        CheckConstraint("min_amount >= 0", name="min_amount_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_type: Mapped[str] = mapped_column(String(30), index=True)
    min_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    approver_role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint(_in_list("document_type", DOCUMENT_TYPES), name="document_type"),
        CheckConstraint(_in_list("status", APPROVAL_STATUSES), name="status"),
        Index("ix_approvals_status_role", "status", "approver_role_id"),
        Index("ix_approvals_document", "document_type", "document_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_type: Mapped[str] = mapped_column(String(30))
    document_id: Mapped[int] = mapped_column(Integer)
    document_number: Mapped[str] = mapped_column(String(30))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    rule_id: Mapped[int] = mapped_column(ForeignKey("approval_rules.id"))
    # Snapshot of the rule's approver role when the request was made.
    approver_role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    status: Mapped[str] = mapped_column(String(20), default=PENDING)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    requested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    remark: Mapped[str] = mapped_column(String(500), default="")
