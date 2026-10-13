from datetime import date

from fastapi import APIRouter, Request

from app.core.deps import Allow, DbDep
from app.core.pagination import Page, PageParamsDep
from app.modules.employees import service
from app.modules.employees.schemas import (
    AttendanceIn,
    AttendanceSheetOut,
    EmployeeIn,
    EmployeeOut,
    GenerateIn,
    Month,
    PayIn,
    PayrollRunOut,
    PayrollStatus,
    PayrollUpdateIn,
)

router = APIRouter(prefix="/employees", tags=["employees"])


def _employee(db: DbDep, employee_id: int) -> EmployeeOut:
    return EmployeeOut(**service.employees_out(db, [service.get_employee(db, employee_id)])[0])


def _run(db: DbDep, run_id: int) -> PayrollRunOut:
    return PayrollRunOut(**service.runs_out(db, [service.get_run(db, run_id)])[0])


# --- attendance & payroll (declared before /{employee_id}) -----------------------------


@router.get("/attendance")
def attendance_sheet(
    db: DbDep, _: Allow("attendance.view"), attendance_date: date | None = None
) -> AttendanceSheetOut:
    return AttendanceSheetOut(**service.attendance_sheet(db, attendance_date or service.today()))


@router.put("/attendance")
def mark_attendance(
    data: AttendanceIn, db: DbDep, user: Allow("attendance.edit"), request: Request
) -> AttendanceSheetOut:
    return AttendanceSheetOut(**service.mark_attendance(db, user, data, request))


@router.get("/payroll")
def list_runs(
    db: DbDep,
    params: PageParamsDep,
    _: Allow("payroll.view"),
    month: Month | None = None,
    status: PayrollStatus | None = None,
) -> Page[PayrollRunOut]:
    return Page[PayrollRunOut](**service.list_runs(db, params, month, status))


@router.post("/payroll", status_code=201)
def generate(
    data: GenerateIn, db: DbDep, user: Allow("payroll.create"), request: Request
) -> PayrollRunOut:
    return _run(db, service.generate_payroll(db, user, data.month, request).id)


@router.get("/payroll/{run_id}")
def get_run(run_id: int, db: DbDep, _: Allow("payroll.view")) -> PayrollRunOut:
    return _run(db, run_id)


@router.put("/payroll/{run_id}")
def update_run(
    run_id: int, data: PayrollUpdateIn, db: DbDep, user: Allow("payroll.edit"), request: Request
) -> PayrollRunOut:
    return _run(db, service.update_payroll(db, user, run_id, data, request).id)


@router.post("/payroll/{run_id}/pay")
def pay_run(
    run_id: int, data: PayIn, db: DbDep, user: Allow("payroll.edit"), request: Request
) -> PayrollRunOut:
    return _run(db, service.pay_payroll(db, user, run_id, data, request).id)


@router.post("/payroll/{run_id}/cancel")
def cancel_run(
    run_id: int, db: DbDep, user: Allow("payroll.delete"), request: Request
) -> PayrollRunOut:
    return _run(db, service.cancel_payroll(db, user, run_id, request).id)


# --- employees -------------------------------------------------------------------------


@router.get("")
def list_employees(
    db: DbDep,
    params: PageParamsDep,
    _: Allow("employee.view"),
    is_active: bool | None = None,
    department: str | None = None,
) -> Page[EmployeeOut]:
    return Page[EmployeeOut](**service.list_employees(db, params, is_active, department))


@router.post("", status_code=201)
def create_employee(
    data: EmployeeIn, db: DbDep, user: Allow("employee.create"), request: Request
) -> EmployeeOut:
    return _employee(db, service.create_employee(db, user, data, request).id)


@router.get("/{employee_id}")
def get_employee(employee_id: int, db: DbDep, _: Allow("employee.view")) -> EmployeeOut:
    return _employee(db, employee_id)


@router.put("/{employee_id}")
def update_employee(
    employee_id: int, data: EmployeeIn, db: DbDep, user: Allow("employee.edit"), request: Request
) -> EmployeeOut:
    return _employee(db, service.update_employee(db, user, employee_id, data, request).id)


@router.post("/{employee_id}/deactivate")
def deactivate(
    employee_id: int, db: DbDep, user: Allow("employee.delete"), request: Request
) -> EmployeeOut:
    return _employee(db, service.set_employee_active(db, user, employee_id, False, request).id)


@router.post("/{employee_id}/activate")
def activate(
    employee_id: int, db: DbDep, user: Allow("employee.delete"), request: Request
) -> EmployeeOut:
    return _employee(db, service.set_employee_active(db, user, employee_id, True, request).id)
