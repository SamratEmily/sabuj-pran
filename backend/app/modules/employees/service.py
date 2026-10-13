"""Employees (simple): employee records, daily attendance and a basic monthly payroll.

Payroll: absence_deduction = base_salary / 30 x absent days (leave and late don't deduct),
net = base - absence deduction - other deduction + bonus. Paying a run is one transaction:
one PAYROLL money OUT for the total through the money engine (`money.money_out`, which
blocks a negative balance) and the run marked paid; paid runs are frozen.
"""

import calendar
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.dates import today
from app.core.db import atomic, utcnow
from app.core.errors import AppError
from app.core.numbering import next_document_number, next_free_code
from app.core.pagination import PageParams
from app.modules.auth.models import User
from app.modules.employees.models import (
    ABSENT,
    ATTENDANCE_STATUSES,
    CANCELLED,
    DRAFT,
    PAID,
    PRESENT,
    Attendance,
    Employee,
    PayrollItem,
    PayrollRun,
)
from app.modules.employees.schemas import AttendanceIn, EmployeeIn, PayIn, PayrollUpdateIn
from app.modules.master.models import ExpenseCategory
from app.modules.money import service as money
from app.modules.money.models import PAYROLL, MoneyAccount

Q2 = Decimal("0.01")
ZERO = Decimal("0")
DAYS_PER_MONTH = Decimal("30")
EMPLOYEE_CODE_SEQUENCE = "EMP"
SALARY_CATEGORY = "Salary"


def _money(value: Decimal) -> Decimal:
    return value.quantize(Q2, ROUND_HALF_UP)


def absence_deduction(base_salary: Decimal, absent_days: int) -> Decimal:
    """base / 30 per absent day, never more than the base salary."""
    return min(base_salary, _money(base_salary / DAYS_PER_MONTH * absent_days))


# =========================================================================================
# Employees
# =========================================================================================


def _values(db: Session, data: EmployeeIn, exclude_id: int | None) -> dict[str, Any]:
    values = data.model_dump(exclude={"code"})
    values["mobile"] = values["mobile"] or ""
    values["email"] = values["email"] or ""
    if data.user_id is not None:
        if db.get(User, data.user_id) is None:
            raise AppError(400, "INVALID_USER", "Choose an existing user")
        stmt = select(Employee.id).where(Employee.user_id == data.user_id)
        if exclude_id is not None:
            stmt = stmt.where(Employee.id != exclude_id)
        if db.scalar(stmt) is not None:
            raise AppError(409, "USER_TAKEN", "That user is already linked to another employee")
    return values


def _check_code(db: Session, code: str, exclude_id: int | None) -> None:
    stmt = select(Employee.id).where(Employee.code == code)
    if exclude_id is not None:
        stmt = stmt.where(Employee.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise AppError(409, "CODE_TAKEN", f"Employee code '{code}' is already in use")


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(409, "CODE_TAKEN", "Employee code or user link is already in use") from exc


def employees_out(db: Session, employees: list[Employee]) -> list[dict[str, Any]]:
    user_ids = [e.user_id for e in employees if e.user_id]
    users = (
        {u.id: u.username for u in db.scalars(select(User).where(User.id.in_(user_ids)))}
        if user_ids
        else {}
    )
    return [
        {
            "id": e.id,
            "code": e.code,
            "full_name": e.full_name,
            "mobile": e.mobile,
            "email": e.email,
            "designation": e.designation,
            "department": e.department,
            "joining_date": e.joining_date,
            "base_salary": e.base_salary,
            "is_active": e.is_active,
            "user_id": e.user_id,
            "username": users.get(e.user_id) if e.user_id else None,
        }
        for e in employees
    ]


def get_employee(db: Session, employee_id: int) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise AppError(404, "NOT_FOUND", "Employee not found")
    return employee


def list_employees(
    db: Session,
    params: PageParams,
    is_active: bool | None = None,
    department: str | None = None,
) -> dict[str, Any]:
    stmt = select(Employee).order_by(Employee.code)
    if is_active is not None:
        stmt = stmt.where(Employee.is_active.is_(is_active))
    if department:
        stmt = stmt.where(Employee.department == department)
    if params.search:
        term = params.search
        stmt = stmt.where(
            or_(
                Employee.code.contains(term, autoescape=True),
                Employee.full_name.contains(term, autoescape=True),
                Employee.mobile.contains(term, autoescape=True),
                Employee.designation.contains(term, autoescape=True),
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.limit(params.page_size).offset(params.offset)))
    return {
        "items": employees_out(db, rows),
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
    }


def create_employee(
    db: Session, user: User, data: EmployeeIn, request: Request | None = None
) -> Employee:
    values = _values(db, data, None)
    if data.code:
        _check_code(db, data.code, None)
        values["code"] = data.code
    else:
        values["code"] = next_free_code(db, EMPLOYEE_CODE_SEQUENCE, Employee.code)
    employee = Employee(**values, is_active=True)
    db.add(employee)
    db.flush()
    log_audit(
        db,
        user,
        "create",
        "employee",
        employee.id,
        f"Created employee {employee.code} {employee.full_name}",
        new=values,
        request=request,
    )
    _commit(db)
    return employee


def update_employee(
    db: Session, user: User, employee_id: int, data: EmployeeIn, request: Request | None = None
) -> Employee:
    """Salary changes apply to payroll runs generated afterwards."""
    employee = get_employee(db, employee_id)
    values = _values(db, data, employee.id)
    if data.code and data.code != employee.code:
        _check_code(db, data.code, employee.id)
        values["code"] = data.code
    old = {k: getattr(employee, k) for k in values}
    for key, value in values.items():
        setattr(employee, key, value)
    changed = {k: v for k, v in values.items() if old[k] != v}
    log_audit(
        db,
        user,
        "update",
        "employee",
        employee.id,
        f"Updated employee {employee.code}: {', '.join(changed) or 'no changes'}",
        old={k: old[k] for k in changed},
        new=changed,
        request=request,
    )
    _commit(db)
    return employee


def set_employee_active(
    db: Session, user: User, employee_id: int, active: bool, request: Request | None = None
) -> Employee:
    """Employees are never deleted (attendance and payroll keep pointing at them)."""
    employee = get_employee(db, employee_id)
    employee.is_active = active
    log_audit(
        db,
        user,
        "update" if active else "deactivate",
        "employee",
        employee.id,
        f"{'Activated' if active else 'Deactivated'} employee {employee.code}",
        new={"is_active": active},
        request=request,
    )
    db.commit()
    return employee


# =========================================================================================
# Attendance
# =========================================================================================


def attendance_sheet(db: Session, day: date) -> dict[str, Any]:
    """All active employees for `day` (plus inactive ones already marked that day); rows not
    marked yet come pre-filled as present (saved=False)."""
    marked = {
        a.employee_id: a.status
        for a in db.scalars(select(Attendance).where(Attendance.attendance_date == day))
    }
    employees = list(
        db.scalars(
            select(Employee)
            .where(or_(Employee.is_active.is_(True), Employee.id.in_(list(marked) or [0])))
            .order_by(Employee.code)
        )
    )
    rows = [
        {
            "employee_id": e.id,
            "employee_code": e.code,
            "employee_name": e.full_name,
            "designation": e.designation,
            "department": e.department,
            "status": marked.get(e.id, PRESENT),
            "saved": e.id in marked,
        }
        for e in employees
    ]
    summary = {s: sum(1 for r in rows if r["status"] == s) for s in ATTENDANCE_STATUSES}
    return {"attendance_date": day, "rows": rows, "summary": summary}


def mark_attendance(
    db: Session, user: User, data: AttendanceIn, request: Request | None = None
) -> dict[str, Any]:
    """Insert or update one row per employee for the date (bulk or a single row)."""
    if data.attendance_date > today():
        raise AppError(400, "FUTURE_DATE", "Attendance can't be marked for a future date")
    ids = [e.employee_id for e in data.entries]
    if len(ids) != len(set(ids)):
        raise AppError(400, "DUPLICATE_LINE", "Each employee may appear only once")
    with atomic(db):
        employees = {e.id: e for e in db.scalars(select(Employee).where(Employee.id.in_(ids)))}
        existing = {
            a.employee_id: a
            for a in db.scalars(
                select(Attendance)
                .where(
                    Attendance.attendance_date == data.attendance_date,
                    Attendance.employee_id.in_(ids),
                )
                .with_for_update()
            )
        }
        changes = 0
        for entry in data.entries:
            employee = employees.get(entry.employee_id)
            if employee is None:
                raise AppError(400, "INVALID_EMPLOYEE", f"Employee {entry.employee_id} not found")
            row = existing.get(entry.employee_id)
            if row is None:
                if not employee.is_active:
                    raise AppError(
                        400, "INACTIVE_EMPLOYEE", f"Employee {employee.code} is inactive"
                    )
                db.add(
                    Attendance(
                        employee_id=employee.id,
                        attendance_date=data.attendance_date,
                        status=entry.status,
                        marked_by=user.id,
                    )
                )
                changes += 1
            elif row.status != entry.status:
                row.status = entry.status
                row.marked_by = user.id
                changes += 1
        db.flush()
        log_audit(
            db,
            user,
            "update",
            "attendance",
            None,
            f"Attendance {data.attendance_date}: {changes} change(s) for {len(ids)} employee(s)",
            new={"date": data.attendance_date, "entries": [e.model_dump() for e in data.entries]},
            request=request,
        )
    return attendance_sheet(db, data.attendance_date)


def absent_days(db: Session, month: str) -> dict[int, int]:
    year, mon = (int(x) for x in month.split("-"))
    first = date(year, mon, 1)
    last = date(year, mon, calendar.monthrange(year, mon)[1])
    return dict(
        db.execute(
            select(Attendance.employee_id, func.count())
            .where(
                Attendance.status == ABSENT,
                Attendance.attendance_date >= first,
                Attendance.attendance_date <= last,
            )
            .group_by(Attendance.employee_id)
        ).all()
    )


# =========================================================================================
# Payroll
# =========================================================================================


def _lock_run(db: Session, run_id: int) -> PayrollRun:
    run = db.scalar(
        select(PayrollRun)
        .where(PayrollRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if run is None:
        raise AppError(404, "NOT_FOUND", "Payroll run not found")
    return run


def _require_draft(run: PayrollRun, action: str) -> None:
    if run.status != DRAFT:
        raise AppError(
            400, "INVALID_STATUS", f"Cannot {action} {run.prl_number}: it is {run.status}"
        )


def _net(item: PayrollItem) -> Decimal:
    return item.base_salary - item.absence_deduction - item.other_deduction + item.bonus


def generate_payroll(
    db: Session, user: User, month: str, request: Request | None = None
) -> PayrollRun:
    """Draft run for every active employee with their absent days of the month."""
    try:
        with atomic(db):
            if db.scalar(select(PayrollRun.id).where(PayrollRun.live_month == month)):
                raise AppError(
                    409, "PAYROLL_EXISTS", f"A payroll for {month} already exists; cancel it first"
                )
            employees = list(
                db.scalars(
                    select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.code)
                )
            )
            if not employees:
                raise AppError(400, "NO_EMPLOYEES", "There are no active employees")
            absences = absent_days(db, month)
            run = PayrollRun(
                prl_number=next_document_number(db, "PRL"),
                month=month,
                live_month=month,
                status=DRAFT,
                total_net=ZERO,
                created_by=user.id,
            )
            for e in employees:
                days = absences.get(e.id, 0)
                item = PayrollItem(
                    employee_id=e.id,
                    base_salary=e.base_salary,
                    absent_days=days,
                    absence_deduction=absence_deduction(e.base_salary, days),
                    bonus=ZERO,
                    other_deduction=ZERO,
                )
                item.net_pay = _net(item)
                run.items.append(item)
            run.total_net = sum((i.net_pay for i in run.items), ZERO)
            db.add(run)
            db.flush()
            log_audit(
                db,
                user,
                "create",
                "payroll",
                run.id,
                f"Generated {run.prl_number} for {month}: {len(run.items)} employees, "
                f"{run.total_net:,.2f}",
                new={"month": month, "total_net": run.total_net},
                request=request,
            )
    except IntegrityError as exc:  # a concurrent run for the same month won the unique index
        raise AppError(
            409, "PAYROLL_EXISTS", f"A payroll for {month} already exists; cancel it first"
        ) from exc
    return run


def update_payroll(
    db: Session, user: User, run_id: int, data: PayrollUpdateIn, request: Request | None = None
) -> PayrollRun:
    """Edit bonus / other deduction of draft lines."""
    with atomic(db):
        run = _lock_run(db, run_id)
        _require_draft(run, "edit")
        by_id = {i.id: i for i in run.items}
        for change in data.items:
            item = by_id.get(change.id)
            if item is None:
                raise AppError(400, "INVALID_LINE", f"Line {change.id} is not on {run.prl_number}")
            bonus, deduction = change.bonus, change.other_deduction
            net = item.base_salary - item.absence_deduction - deduction + bonus
            if net < 0:
                raise AppError(
                    400,
                    "NEGATIVE_NET_PAY",
                    f"Deductions are more than the pay of line {item.id}",
                )
            item.bonus, item.other_deduction, item.net_pay = bonus, deduction, net
        run.total_net = sum((i.net_pay for i in run.items), ZERO)
        log_audit(
            db,
            user,
            "update",
            "payroll",
            run.id,
            f"Updated {run.prl_number}: total {run.total_net:,.2f}",
            new={"items": [i.model_dump() for i in data.items], "total_net": run.total_net},
            request=request,
        )
    return run


def pay_payroll(
    db: Session, user: User, run_id: int, data: PayIn, request: Request | None = None
) -> PayrollRun:
    """One PAYROLL money OUT for the total + run marked paid, in one transaction."""
    with atomic(db):
        run = _lock_run(db, run_id)
        if run.status == PAID:
            raise AppError(400, "ALREADY_PAID", f"{run.prl_number} is already paid")
        _require_draft(run, "pay")
        if run.total_net <= 0:
            raise AppError(400, "NOTHING_TO_PAY", f"{run.prl_number} has nothing to pay")
        money._active_account(db, data.account_id)
        when = data.payment_date or today()
        money.money_out(
            db,
            data.account_id,
            run.total_net,
            PAYROLL,
            PAYROLL,
            run.id,
            when,
            user,
            f"{run.prl_number} salaries {run.month}",
        )
        run.status = PAID
        run.paid_by = user.id
        run.paid_at = utcnow()
        run.payment_date = when
        run.account_id = data.account_id
        run.expense_category_id = db.scalar(
            select(ExpenseCategory.id).where(ExpenseCategory.name == SALARY_CATEGORY)
        )
        log_audit(
            db,
            user,
            "post",
            "payroll",
            run.id,
            f"Paid {run.prl_number}: {run.total_net:,.2f}",
            new={"account_id": data.account_id, "payment_date": when},
            request=request,
        )
    return run


def cancel_payroll(
    db: Session, user: User, run_id: int, request: Request | None = None
) -> PayrollRun:
    """Drop a draft run (e.g. to regenerate after attendance corrections)."""
    with atomic(db):
        run = _lock_run(db, run_id)
        _require_draft(run, "cancel")
        run.status = CANCELLED
        run.live_month = None
        log_audit(
            db,
            user,
            "cancel",
            "payroll",
            run.id,
            f"Cancelled {run.prl_number}",
            old={"status": DRAFT},
            new={"status": CANCELLED},
            request=request,
        )
    return run


def runs_out(db: Session, runs: list[PayrollRun]) -> list[dict[str, Any]]:
    employee_ids = {i.employee_id for r in runs for i in r.items}
    employees = (
        {e.id: e for e in db.scalars(select(Employee).where(Employee.id.in_(employee_ids)))}
        if employee_ids
        else {}
    )
    user_ids = {u for r in runs for u in (r.created_by, r.paid_by) if u}
    users = {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_(user_ids)))}
    account_ids = {r.account_id for r in runs if r.account_id}
    accounts = (
        {
            a.id: a.name
            for a in db.scalars(select(MoneyAccount).where(MoneyAccount.id.in_(account_ids)))
        }
        if account_ids
        else {}
    )
    return [
        {
            "id": r.id,
            "prl_number": r.prl_number,
            "month": r.month,
            "status": r.status,
            "total_net": r.total_net,
            "employee_count": len(r.items),
            "created_by_name": users.get(r.created_by, ""),
            "created_at": r.created_at,
            "paid_by_name": users.get(r.paid_by) if r.paid_by else None,
            "paid_at": r.paid_at,
            "payment_date": r.payment_date,
            "account_id": r.account_id,
            "account_name": accounts.get(r.account_id) if r.account_id else None,
            "items": [
                {
                    "id": i.id,
                    "employee_id": i.employee_id,
                    "employee_code": employees[i.employee_id].code,
                    "employee_name": employees[i.employee_id].full_name,
                    "designation": employees[i.employee_id].designation,
                    "base_salary": i.base_salary,
                    "absent_days": i.absent_days,
                    "absence_deduction": i.absence_deduction,
                    "bonus": i.bonus,
                    "other_deduction": i.other_deduction,
                    "net_pay": i.net_pay,
                }
                for i in r.items
            ],
        }
        for r in runs
    ]


def get_run(db: Session, run_id: int) -> PayrollRun:
    run = db.get(PayrollRun, run_id)
    if run is None:
        raise AppError(404, "NOT_FOUND", "Payroll run not found")
    db.refresh(run)
    return run


def list_runs(
    db: Session, params: PageParams, month: str | None = None, status: str | None = None
) -> dict[str, Any]:
    stmt = select(PayrollRun).order_by(PayrollRun.month.desc(), PayrollRun.id.desc())
    if month:
        stmt = stmt.where(PayrollRun.month == month)
    if status:
        stmt = stmt.where(PayrollRun.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    runs = list(db.scalars(stmt.limit(params.page_size).offset(params.offset)))
    return {
        "items": runs_out(db, runs),
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
    }
