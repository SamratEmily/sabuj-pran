"""Approvals: rules by document type + minimum amount + approver role, and the requests
raised against them.

Modules keep their own posting logic. Each registers a `finalize` (post / approve the
document) and a `reject` handler at import time; this module only decides whether a
document needs approval and, on a decision, runs the registered handler inside the same
transaction as the decision (`atomic` is re-entrant). While a request is pending nothing
is posted.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.dates import local_day_end_utc, local_day_start_utc
from app.core.db import atomic, utcnow
from app.core.errors import AppError
from app.core.pagination import PageParams
from app.modules.approvals.models import (
    APPROVED,
    PENDING,
    REJECTED,
    Approval,
    ApprovalRule,
)
from app.modules.approvals.schemas import RuleIn
from app.modules.auth.models import Role, User
from app.modules.auth.service import ADMIN_ROLE

LABELS = {
    "PURCHASE_ORDER": "Purchase order",
    "EXPENSE": "Expense",
    "SUPPLIER_PAYMENT": "Supplier payment",
    "STOCK_ADJUSTMENT": "Stock adjustment",
}


@dataclass(frozen=True)
class Handler:
    finalize: Callable[[Session, int, User], Any]  # post / approve the document
    reject: Callable[[Session, int, User, str], Any]  # mark it rejected (nothing posted)


_HANDLERS: dict[str, Handler] = {}


def register(
    document_type: str,
    finalize: Callable[[Session, int, User], Any],
    reject: Callable[[Session, int, User, str], Any],
) -> None:
    """Called by each module at import time."""
    _HANDLERS[document_type] = Handler(finalize, reject)


def _handler(document_type: str) -> Handler:
    handler = _HANDLERS.get(document_type)
    if handler is None:  # module not imported: a programming error
        raise RuntimeError(f"No approval handler registered for {document_type}")
    return handler


# =========================================================================================
# Requesting
# =========================================================================================


def matching_rule(db: Session, document_type: str, amount: Decimal) -> ApprovalRule | None:
    """The active rule with the highest min_amount <= amount."""
    return db.scalar(
        select(ApprovalRule)
        .where(
            ApprovalRule.document_type == document_type,
            ApprovalRule.is_active.is_(True),
            ApprovalRule.min_amount <= amount,
        )
        .order_by(ApprovalRule.min_amount.desc(), ApprovalRule.id.desc())
        .limit(1)
    )


def maybe_require_approval(
    db: Session,
    document_type: str,
    document_id: int,
    number: str,
    amount: Decimal,
    requester: User,
    request: Request | None = None,
) -> Approval | None:
    """Raise an approval request when a rule applies (inside the caller's transaction).

    Returns None when no rule matches: the caller finalizes immediately. Otherwise the
    caller must set the document to pending_approval and post nothing.
    """
    rule = matching_rule(db, document_type, amount)
    if rule is None:
        return None
    open_request = db.scalar(
        select(Approval.id).where(
            Approval.document_type == document_type,
            Approval.document_id == document_id,
            Approval.status == PENDING,
        )
    )
    if open_request is not None:
        raise AppError(400, "ALREADY_PENDING", f"{number} is already waiting for approval")
    approval = Approval(
        document_type=document_type,
        document_id=document_id,
        document_number=number,
        amount=amount,
        rule_id=rule.id,
        approver_role_id=rule.approver_role_id,
        status=PENDING,
        requested_by=requester.id,
        remark="",
    )
    db.add(approval)
    db.flush()
    role = db.get(Role, rule.approver_role_id)
    log_audit(
        db,
        requester,
        "create",
        "approval",
        approval.id,
        f"{number} ({amount:,.2f}) sent for approval by {role.name if role else 'approver'}",
        new={"document_type": document_type, "document_id": document_id, "rule_id": rule.id},
        request=request,
    )
    return approval


def pending_for(db: Session, document_type: str, document_id: int) -> Approval | None:
    return db.scalar(
        select(Approval).where(
            Approval.document_type == document_type,
            Approval.document_id == document_id,
            Approval.status == PENDING,
        )
    )


def close_request(db: Session, document_type: str, document_id: int, user: User) -> None:
    """The document was cancelled while pending: close its request (inside the caller's
    transaction) so it no longer shows up for approvers."""
    approval = pending_for(db, document_type, document_id)
    if approval is not None:
        approval.status = REJECTED
        approval.decided_by = user.id
        approval.decided_at = utcnow()
        approval.remark = "Document cancelled before a decision"


# =========================================================================================
# Deciding
# =========================================================================================


def _is_admin(user: User) -> bool:
    return user.role.name == ADMIN_ROLE


def _may_decide(approval: Approval, user: User) -> bool:
    return approval.requested_by != user.id and (
        _is_admin(user) or user.role_id == approval.approver_role_id
    )


def _lock(db: Session, approval_id: int) -> Approval:
    approval = db.scalar(
        select(Approval)
        .where(Approval.id == approval_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if approval is None:
        raise AppError(404, "APPROVAL_NOT_FOUND", "Approval request not found")
    return approval


def _check_decider(db: Session, approval: Approval, user: User) -> None:
    if approval.status != PENDING:
        raise AppError(
            400,
            "ALREADY_DECIDED",
            f"{approval.document_number} was already {approval.status}",
        )
    if approval.requested_by == user.id:
        raise AppError(403, "SELF_APPROVAL", "You cannot approve or reject your own request")
    if not _is_admin(user) and user.role_id != approval.approver_role_id:
        role = db.get(Role, approval.approver_role_id)
        raise AppError(
            403,
            "WRONG_ROLE",
            f"Only {role.name if role else 'the approver role'} can decide on "
            f"{approval.document_number}",
        )


def _decide(
    db: Session,
    approval_id: int,
    user: User,
    remark: str,
    approve: bool,
    request: Request | None,
) -> Approval:
    with atomic(db):
        approval = _lock(db, approval_id)
        _check_decider(db, approval, user)
        handler = _handler(approval.document_type)
        if approve:
            handler.finalize(db, approval.document_id, user)
        else:
            if not remark:
                raise AppError(400, "REMARK_REQUIRED", "Give a reason for the rejection")
            handler.reject(db, approval.document_id, user, remark)
        approval.status = APPROVED if approve else REJECTED
        approval.decided_by = user.id
        approval.decided_at = utcnow()
        approval.remark = remark
        log_audit(
            db,
            user,
            "approve" if approve else "reject",
            "approval",
            approval.id,
            f"{'Approved' if approve else 'Rejected'} {approval.document_number}"
            + (f": {remark}" if remark else ""),
            old={"status": PENDING},
            new={"status": approval.status, "remark": remark},
            request=request,
        )
    return approval


def approve(
    db: Session, approval_id: int, user: User, remark: str = "", request: Request | None = None
) -> Approval:
    """Run the document's finalize and mark the request approved, in one transaction."""
    return _decide(db, approval_id, user, remark, True, request)


def reject(
    db: Session, approval_id: int, user: User, remark: str, request: Request | None = None
) -> Approval:
    return _decide(db, approval_id, user, remark, False, request)


# =========================================================================================
# Rules
# =========================================================================================


def _role(db: Session, role_id: int) -> Role:
    role = db.get(Role, role_id)
    if role is None:
        raise AppError(400, "INVALID_ROLE", "Choose an existing role")
    return role


def rules_out(db: Session, rules: list[ApprovalRule]) -> list[dict[str, Any]]:
    roles = {r.id: r.name for r in db.scalars(select(Role))}
    return [
        {
            "id": r.id,
            "document_type": r.document_type,
            "document_label": LABELS[r.document_type],
            "min_amount": r.min_amount,
            "approver_role_id": r.approver_role_id,
            "approver_role_name": roles.get(r.approver_role_id, ""),
            "is_active": r.is_active,
        }
        for r in rules
    ]


def get_rule(db: Session, rule_id: int) -> ApprovalRule:
    rule = db.get(ApprovalRule, rule_id)
    if rule is None:
        raise AppError(404, "NOT_FOUND", "Approval rule not found")
    return rule


def list_rules(
    db: Session,
    params: PageParams,
    document_type: str | None = None,
    is_active: bool | None = None,
) -> dict[str, Any]:
    stmt = select(ApprovalRule).order_by(ApprovalRule.document_type, ApprovalRule.min_amount)
    if document_type:
        stmt = stmt.where(ApprovalRule.document_type == document_type)
    if is_active is not None:
        stmt = stmt.where(ApprovalRule.is_active.is_(is_active))
    if params.search:
        term = params.search.strip().lower()
        types = [t for t, label in LABELS.items() if term in label.lower() or term in t.lower()]
        role_ids = select(Role.id).where(Role.name.contains(params.search, autoescape=True))
        stmt = stmt.where(
            or_(ApprovalRule.document_type.in_(types), ApprovalRule.approver_role_id.in_(role_ids))
        )
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rules = list(db.scalars(stmt.limit(params.page_size).offset(params.offset)))
    return {
        "items": rules_out(db, rules),
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
    }


def create_rule(
    db: Session, user: User, data: RuleIn, request: Request | None = None
) -> ApprovalRule:
    with atomic(db):
        role = _role(db, data.approver_role_id)
        rule = ApprovalRule(**data.model_dump(), is_active=True)
        db.add(rule)
        db.flush()
        log_audit(
            db,
            user,
            "create",
            "approval_rule",
            rule.id,
            f"Rule: {LABELS[rule.document_type]} >= {rule.min_amount:,.2f} needs {role.name}",
            new=data.model_dump(),
            request=request,
        )
    return rule


def update_rule(
    db: Session, user: User, rule_id: int, data: RuleIn, request: Request | None = None
) -> ApprovalRule:
    """Pending requests keep the approver role they were raised with."""
    with atomic(db):
        rule = get_rule(db, rule_id)
        _role(db, data.approver_role_id)
        old = {
            "document_type": rule.document_type,
            "min_amount": rule.min_amount,
            "approver_role_id": rule.approver_role_id,
        }
        for field, value in data.model_dump().items():
            setattr(rule, field, value)
        log_audit(
            db,
            user,
            "update",
            "approval_rule",
            rule.id,
            f"Updated approval rule {rule.id}",
            old=old,
            new=data.model_dump(),
            request=request,
        )
    return rule


def set_rule_active(
    db: Session, user: User, rule_id: int, active: bool, request: Request | None = None
) -> ApprovalRule:
    with atomic(db):
        rule = get_rule(db, rule_id)
        rule.is_active = active
        log_audit(
            db,
            user,
            "update" if active else "deactivate",
            "approval_rule",
            rule.id,
            f"{'Activated' if active else 'Deactivated'} approval rule {rule.id}",
            new={"is_active": active},
            request=request,
        )
    return rule


# =========================================================================================
# Requests (read side)
# =========================================================================================


def approvals_out(db: Session, approvals: list[Approval], user: User) -> list[dict[str, Any]]:
    roles = {r.id: r.name for r in db.scalars(select(Role))}
    user_ids = {u for a in approvals for u in (a.requested_by, a.decided_by) if u}
    users = (
        {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_(user_ids)))}
        if user_ids
        else {}
    )
    return [
        {
            "id": a.id,
            "document_type": a.document_type,
            "document_label": LABELS[a.document_type],
            "document_id": a.document_id,
            "document_number": a.document_number,
            "amount": a.amount,
            "status": a.status,
            "approver_role_id": a.approver_role_id,
            "approver_role_name": roles.get(a.approver_role_id, ""),
            "requested_by": a.requested_by,
            "requested_by_name": users.get(a.requested_by, ""),
            "requested_at": a.requested_at,
            "decided_by_name": users.get(a.decided_by) if a.decided_by else None,
            "decided_at": a.decided_at,
            "remark": a.remark,
            "can_decide": a.status == PENDING and _may_decide(a, user),
        }
        for a in approvals
    ]


def _pending_stmt(user: User) -> Any:
    stmt = select(Approval).where(Approval.status == PENDING)
    if not _is_admin(user):
        stmt = stmt.where(Approval.approver_role_id == user.role_id)
    return stmt


def pending_count(db: Session, user: User) -> int:
    """Requests waiting for this user's decision (their role; Admin: all, own excluded)."""
    stmt = _pending_stmt(user).where(Approval.requested_by != user.id)
    return db.scalar(select(func.count()).select_from(stmt.subquery())) or 0


def list_approvals(
    db: Session,
    user: User,
    params: PageParams,
    pending: bool,
    document_type: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    """`pending`: what this user's role must decide (Admin: everything pending).
    Otherwise the full history with filters."""
    stmt = _pending_stmt(user) if pending else select(Approval)
    if document_type:
        stmt = stmt.where(Approval.document_type == document_type)
    if status and not pending:
        stmt = stmt.where(Approval.status == status)
    if date_from:
        stmt = stmt.where(Approval.requested_at >= local_day_start_utc(date_from))
    if date_to:
        stmt = stmt.where(Approval.requested_at < local_day_end_utc(date_to))
    if params.search:
        stmt = stmt.where(Approval.document_number.contains(params.search, autoescape=True))
    stmt = stmt.order_by(Approval.id.desc())
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.limit(params.page_size).offset(params.offset)))
    return {
        "items": approvals_out(db, rows, user),
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
    }
