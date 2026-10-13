from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.core.deps import Allow, DbDep
from app.core.pagination import Page, PageParamsDep
from app.modules.approvals import service
from app.modules.approvals.schemas import (
    ApprovalOut,
    ApprovalStatus,
    DecisionIn,
    DocumentType,
    PendingCountOut,
    RuleIn,
    RuleOut,
)

router = APIRouter(prefix="/approvals", tags=["approvals"])

DateFrom = Annotated[date | None, Query(alias="from")]
DateTo = Annotated[date | None, Query(alias="to")]


def _rule(db: DbDep, rule_id: int) -> RuleOut:
    return RuleOut(**service.rules_out(db, [service.get_rule(db, rule_id)])[0])


# --- rules -----------------------------------------------------------------------------


@router.get("/rules")
def list_rules(
    db: DbDep,
    params: PageParamsDep,
    _: Allow("approval_rule.view"),
    document_type: DocumentType | None = None,
    is_active: bool | None = None,
) -> Page[RuleOut]:
    return Page[RuleOut](**service.list_rules(db, params, document_type, is_active))


@router.post("/rules", status_code=201)
def create_rule(
    data: RuleIn, db: DbDep, user: Allow("approval_rule.create"), request: Request
) -> RuleOut:
    return _rule(db, service.create_rule(db, user, data, request).id)


@router.get("/rules/{rule_id}")
def get_rule(rule_id: int, db: DbDep, _: Allow("approval_rule.view")) -> RuleOut:
    return _rule(db, rule_id)


@router.put("/rules/{rule_id}")
def update_rule(
    rule_id: int, data: RuleIn, db: DbDep, user: Allow("approval_rule.edit"), request: Request
) -> RuleOut:
    return _rule(db, service.update_rule(db, user, rule_id, data, request).id)


@router.post("/rules/{rule_id}/deactivate")
def deactivate_rule(
    rule_id: int, db: DbDep, user: Allow("approval_rule.delete"), request: Request
) -> RuleOut:
    return _rule(db, service.set_rule_active(db, user, rule_id, False, request).id)


@router.post("/rules/{rule_id}/activate")
def activate_rule(
    rule_id: int, db: DbDep, user: Allow("approval_rule.delete"), request: Request
) -> RuleOut:
    return _rule(db, service.set_rule_active(db, user, rule_id, True, request).id)


# --- requests --------------------------------------------------------------------------


@router.get("/pending")
def list_pending(
    db: DbDep,
    params: PageParamsDep,
    user: Allow("approval.view"),
    document_type: DocumentType | None = None,
) -> Page[ApprovalOut]:
    return Page[ApprovalOut](**service.list_approvals(db, user, params, True, document_type))


@router.get("/pending/count")
def pending_count(db: DbDep, user: Allow("approval.view")) -> PendingCountOut:
    return PendingCountOut(count=service.pending_count(db, user))


@router.get("/history")
def history(
    db: DbDep,
    params: PageParamsDep,
    user: Allow("approval.view"),
    document_type: DocumentType | None = None,
    status: ApprovalStatus | None = None,
    date_from: DateFrom = None,
    date_to: DateTo = None,
) -> Page[ApprovalOut]:
    return Page[ApprovalOut](
        **service.list_approvals(db, user, params, False, document_type, status, date_from, date_to)
    )


@router.post("/{approval_id}/approve")
def approve(
    approval_id: int,
    data: DecisionIn,
    db: DbDep,
    user: Allow("approval.approve"),
    request: Request,
) -> ApprovalOut:
    approval = service.approve(db, approval_id, user, data.remark, request)
    return ApprovalOut(**service.approvals_out(db, [approval], user)[0])


@router.post("/{approval_id}/reject")
def reject(
    approval_id: int,
    data: DecisionIn,
    db: DbDep,
    user: Allow("approval.approve"),
    request: Request,
) -> ApprovalOut:
    approval = service.reject(db, approval_id, user, data.remark, request)
    return ApprovalOut(**service.approvals_out(db, [approval], user)[0])
