from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, StringConstraints

from app.core.schemas import Money, UtcDateTime
from app.modules.parties.schemas import Email, Mobile, PartyCode, _blank_to_none

AttendanceStatus = Literal["present", "absent", "leave", "late"]
PayrollStatus = Literal["draft", "paid", "cancelled"]
Month = Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
Text100 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
Amount = Annotated[Money, Field(ge=Decimal("0"))]


# --- employees -------------------------------------------------------------------------


class EmployeeIn(BaseModel):
    # Blank on create -> generated (EMP-0001). Blank on update keeps the code.
    code: Annotated[PartyCode | None, BeforeValidator(_blank_to_none)] = None
    full_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
    ]
    mobile: Annotated[Mobile | None, BeforeValidator(_blank_to_none)] = None
    email: Annotated[Email | None, BeforeValidator(_blank_to_none)] = None
    designation: Text100 = ""
    department: Text100 = ""
    joining_date: date | None = None
    base_salary: Amount = Decimal("0")
    user_id: int | None = None


class EmployeeOut(BaseModel):
    id: int
    code: str
    full_name: str
    mobile: str
    email: str
    designation: str
    department: str
    joining_date: date | None
    base_salary: Money
    is_active: bool
    user_id: int | None
    username: str | None


# --- attendance ------------------------------------------------------------------------


class AttendanceEntryIn(BaseModel):
    employee_id: int
    status: AttendanceStatus


class AttendanceIn(BaseModel):
    attendance_date: date
    entries: list[AttendanceEntryIn] = Field(min_length=1, max_length=2000)


class AttendanceRow(BaseModel):
    employee_id: int
    employee_code: str
    employee_name: str
    designation: str
    department: str
    status: AttendanceStatus
    saved: bool  # False: not marked yet for this date (pre-filled as present)


class AttendanceSheetOut(BaseModel):
    attendance_date: date
    rows: list[AttendanceRow]
    summary: dict[str, int]


# --- payroll ---------------------------------------------------------------------------


class GenerateIn(BaseModel):
    month: Month


class PayrollItemIn(BaseModel):
    id: int
    bonus: Amount = Decimal("0")
    other_deduction: Amount = Decimal("0")


class PayrollUpdateIn(BaseModel):
    items: list[PayrollItemIn] = Field(min_length=1, max_length=2000)


class PayIn(BaseModel):
    account_id: int
    payment_date: date | None = None


class PayrollItemOut(BaseModel):
    id: int
    employee_id: int
    employee_code: str
    employee_name: str
    designation: str
    base_salary: Money
    absent_days: int
    absence_deduction: Money
    bonus: Money
    other_deduction: Money
    net_pay: Money


class PayrollRunOut(BaseModel):
    id: int
    prl_number: str
    month: str
    status: PayrollStatus
    total_net: Money
    employee_count: int
    created_by_name: str
    created_at: UtcDateTime
    paid_by_name: str | None
    paid_at: UtcDateTime | None
    payment_date: date | None
    account_id: int | None
    account_name: str | None
    items: list[PayrollItemOut]
