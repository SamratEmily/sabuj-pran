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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin

MONEY = Numeric(18, 2)
ZERO = Decimal("0")

PRESENT = "present"
ABSENT = "absent"
LEAVE = "leave"
LATE = "late"
ATTENDANCE_STATUSES = (PRESENT, ABSENT, LEAVE, LATE)

DRAFT = "draft"
PAID = "paid"
CANCELLED = "cancelled"
PAYROLL_STATUSES = (DRAFT, PAID, CANCELLED)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(repr(v) for v in values) + ")"


class Employee(TimestampMixin, Base):
    __tablename__ = "employees"
    __table_args__ = (CheckConstraint("base_salary >= 0", name="salary_non_negative"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    full_name: Mapped[str] = mapped_column(String(150), index=True)
    mobile: Mapped[str] = mapped_column(String(20), default="")
    email: Mapped[str] = mapped_column(String(150), default="")
    designation: Mapped[str] = mapped_column(String(100), default="")
    department: Mapped[str] = mapped_column(String(100), default="")
    joining_date: Mapped[date | None] = mapped_column(Date)
    base_salary: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Optional link to a login account (one employee per user).
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True)


class Attendance(TimestampMixin, Base):
    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint("employee_id", "attendance_date", name="employee_date"),
        CheckConstraint(_in_list("status", ATTENDANCE_STATUSES), name="status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    attendance_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(10))
    marked_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


class PayrollRun(TimestampMixin, Base):
    __tablename__ = "payroll_runs"
    __table_args__ = (
        CheckConstraint(_in_list("status", PAYROLL_STATUSES), name="status"),
        CheckConstraint("total_net >= 0", name="total_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prl_number: Mapped[str] = mapped_column(String(30), unique=True)
    month: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    # = month while not cancelled, NULL once cancelled: the unique index allows only one
    # live run per month even under concurrent generation.
    live_month: Mapped[str | None] = mapped_column(String(7), unique=True)
    status: Mapped[str] = mapped_column(String(10), default=DRAFT)
    total_net: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    paid_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)
    payment_date: Mapped[date | None] = mapped_column(Date)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("money_accounts.id"))
    # Counted as this expense category (Salary) in expense figures.
    expense_category_id: Mapped[int | None] = mapped_column(ForeignKey("expense_categories.id"))

    items: Mapped[list["PayrollItem"]] = relationship(
        order_by="PayrollItem.id", cascade="all, delete-orphan"
    )


class PayrollItem(Base):
    __tablename__ = "payroll_items"
    __table_args__ = (
        UniqueConstraint("run_id", "employee_id", name="run_employee"),
        CheckConstraint("absent_days >= 0", name="absent_non_negative"),
        CheckConstraint("bonus >= 0 AND other_deduction >= 0", name="adjustments_non_negative"),
        CheckConstraint("net_pay >= 0", name="net_non_negative"),
        CheckConstraint(
            "net_pay = base_salary - absence_deduction - other_deduction + bonus", name="net"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("payroll_runs.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    base_salary: Mapped[Decimal] = mapped_column(MONEY)
    absent_days: Mapped[int] = mapped_column(Integer, default=0)
    absence_deduction: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    bonus: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    other_deduction: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    net_pay: Mapped[Decimal] = mapped_column(MONEY)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
