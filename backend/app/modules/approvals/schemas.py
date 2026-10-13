from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.core.schemas import Money, UtcDateTime

DocumentType = Literal["PURCHASE_ORDER", "EXPENSE", "SUPPLIER_PAYMENT", "STOCK_ADJUSTMENT"]
ApprovalStatus = Literal["pending", "approved", "rejected"]
Remark = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class RuleIn(BaseModel):
    document_type: DocumentType
    min_amount: Annotated[Money, Field(ge=Decimal("0"))]
    approver_role_id: int


class RuleOut(BaseModel):
    id: int
    document_type: DocumentType
    document_label: str
    min_amount: Money
    approver_role_id: int
    approver_role_name: str
    is_active: bool


class DecisionIn(BaseModel):
    remark: Remark = ""


class ApprovalOut(BaseModel):
    id: int
    document_type: DocumentType
    document_label: str
    document_id: int
    document_number: str
    amount: Money
    status: ApprovalStatus
    approver_role_id: int
    approver_role_name: str
    requested_by: int
    requested_by_name: str
    requested_at: UtcDateTime
    decided_by_name: str | None
    decided_at: UtcDateTime | None
    remark: str
    can_decide: bool  # for the current user: right role (or Admin) and not the requester


class PendingCountOut(BaseModel):
    count: int
