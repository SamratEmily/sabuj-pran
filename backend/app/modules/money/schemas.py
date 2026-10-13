from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.core.pagination import Page
from app.core.schemas import Money, UtcDateTime

Amount = Annotated[Money, Field(gt=Decimal("0"))]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Ref = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
AccountType = Literal["cash", "bank", "mfs"]
VoucherStatus = Literal["draft", "pending_approval", "posted", "reversed", "rejected"]


# --- accounts --------------------------------------------------------------------------


class AccountUpdateIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    account_type: AccountType
    payment_method_id: int | None = None
    account_number: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] = ""


class AccountCreateIn(AccountUpdateIn):
    opening_balance: Annotated[Money, Field(ge=Decimal("0"))] = Decimal("0")


class AccountOut(BaseModel):
    id: int
    name: str
    account_type: AccountType
    payment_method_id: int | None
    payment_method_name: str | None
    account_number: str
    opening_balance: Money
    balance: Money
    is_active: bool
    has_transactions: bool


class PositionOut(BaseModel):
    cash: Money
    bank: Money
    mfs: Money
    total: Money


class AccountLedgerRow(BaseModel):
    id: int
    txn_date: date
    txn_type: str
    direction: Literal["in", "out"]
    amount: Money
    money_in: Money
    money_out: Money
    balance_after: Money
    running_balance: Money
    ref_type: str
    ref_id: int | None
    note: str
    reversal_of_id: int | None
    created_by_name: str | None
    created_at: UtcDateTime


class AccountLedgerPage(Page[AccountLedgerRow]):
    account_id: int
    account_name: str
    opening_balance: Money
    closing_balance: Money


# --- vouchers --------------------------------------------------------------------------


class CollectionIn(BaseModel):
    customer_id: int
    account_id: int
    amount: Amount
    collection_date: date | None = None
    invoice_id: int | None = None
    reference_no: Ref = ""
    notes: Notes = ""


class SupplierPaymentIn(BaseModel):
    supplier_id: int
    account_id: int
    amount: Amount
    payment_date: date | None = None
    reference_no: Ref = ""
    notes: Notes = ""


class ExpenseIn(BaseModel):
    expense_category_id: int
    account_id: int
    amount: Amount
    expense_date: date | None = None
    paid_to: Annotated[str, StringConstraints(strip_whitespace=True, max_length=150)] = ""
    notes: Notes = ""


class IncomeIn(BaseModel):
    income_category_id: int
    account_id: int
    amount: Amount
    income_date: date | None = None
    notes: Notes = ""


class TransferIn(BaseModel):
    from_account_id: int
    to_account_id: int
    amount: Amount
    transfer_date: date | None = None
    notes: Notes = ""


class ReverseIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] = ""


class VoucherOut(BaseModel):
    """One shape for every voucher type; fields not relevant to a type are null."""

    id: int
    number: str
    voucher_date: date
    amount: Money
    status: VoucherStatus
    account_id: int | None
    account_name: str | None
    # collections / supplier payments
    party_id: int | None = None
    party_code: str | None = None
    party_name: str | None = None
    party_due: Money | None = None  # current due of the party (detail only)
    reference_no: str | None = None
    invoice_id: int | None = None
    invoice_number: str | None = None
    # expenses / income
    category_id: int | None = None
    category_name: str | None = None
    paid_to: str | None = None
    # transfers
    from_account_id: int | None = None
    from_account_name: str | None = None
    to_account_id: int | None = None
    to_account_name: str | None = None
    notes: str
    created_by_name: str
    created_at: UtcDateTime
    reversed_by_name: str | None
    reversed_at: UtcDateTime | None
    reversal_reason: str
