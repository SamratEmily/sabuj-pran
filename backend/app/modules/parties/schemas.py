from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, StringConstraints

from app.core.schemas import Money, UtcDateTime

PartyType = Literal["customer", "supplier"]


def _blank_to_none(v: object) -> object:
    if isinstance(v, str):
        return v.strip() or None
    return v


PartyCode = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9/_.-]{1,20}$")]
Email = Annotated[str, StringConstraints(max_length=150, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
Mobile = Annotated[str, StringConstraints(pattern=r"^\+?[0-9]{6,19}$")]


class PartyIn(BaseModel):
    # Blank on create -> generated (CUS-0001 / SUP-0001). Blank on update keeps the code.
    code: Annotated[PartyCode | None, BeforeValidator(_blank_to_none)] = None
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
    contact_person: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] = ""
    mobile: Annotated[Mobile | None, BeforeValidator(_blank_to_none)] = None
    email: Annotated[Email | None, BeforeValidator(_blank_to_none)] = None
    address: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
    opening_due: Annotated[Money, Field(ge=Decimal("0"))] = Decimal("0")
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ""


class PartyOut(BaseModel):
    id: int
    code: str
    name: str
    contact_person: str
    mobile: str
    email: str
    address: str
    opening_due: Money
    notes: str
    is_active: bool
    due: Money
    # True once the party has ledger entries other than its opening balance; the opening
    # due is then locked.
    has_transactions: bool
    created_at: UtcDateTime


class StatementParty(BaseModel):
    id: int
    code: str
    name: str
    mobile: str
    address: str


class StatementEntry(BaseModel):
    id: int
    entry_date: date
    ref_type: str
    ref_id: int | None
    note: str
    debit: Money
    credit: Money
    balance: Money


class StatementOut(BaseModel):
    party_type: PartyType
    party: StatementParty
    date_from: date | None
    date_to: date | None
    opening_balance: Money
    entries: list[StatementEntry]
    total_debit: Money
    total_credit: Money
    closing_balance: Money
