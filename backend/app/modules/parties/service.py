from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import Table, case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.dates import today
from app.core.errors import AppError
from app.core.numbering import next_free_code
from app.core.pagination import PageParams, paginate
from app.modules.auth.models import User
from app.modules.parties.models import (
    CUSTOMER,
    SUPPLIER,
    Customer,
    PartyLedger,
    Supplier,
    v_customer_due,
    v_supplier_due,
)
from app.modules.parties.schemas import (
    PartyIn,
    PartyOut,
    StatementEntry,
    StatementOut,
    StatementParty,
)

ZERO = Decimal("0.00")
OPENING = "OPENING"
OPENING_REVERSAL = "OPENING_REVERSAL"
OPENING_REF_TYPES = (OPENING, OPENING_REVERSAL)


@dataclass(frozen=True)
class PartyKind:
    party_type: str
    model: type[Customer] | type[Supplier]
    code_sequence: str
    label: str
    due_view: Table
    due_view_id: str
    # Side on which a positive due is recorded: customers owe us (debit), we owe suppliers
    # (credit).
    due_side: str


CUSTOMERS = PartyKind(CUSTOMER, Customer, "CUS", "Customer", v_customer_due, "customer_id", "debit")
SUPPLIERS = PartyKind(
    SUPPLIER, Supplier, "SUP", "Supplier", v_supplier_due, "supplier_id", "credit"
)
KINDS = {CUSTOMER: CUSTOMERS, SUPPLIER: SUPPLIERS}


# =========================================================================================
# Ledger primitives (used by sales, purchase and money postings)
# =========================================================================================


def _signed(party_type: str) -> Any:
    """SQL expression for one row's effect on the due, per BUSINESS_RULES.md."""
    if party_type == CUSTOMER:
        return PartyLedger.debit - PartyLedger.credit
    return PartyLedger.credit - PartyLedger.debit


def _party_exists(db: Session, party_type: str, party_id: int) -> bool:
    kind = KINDS.get(party_type)
    return kind is not None and db.get(kind.model, party_id) is not None


def post_party_entry(
    db: Session,
    party_type: str,
    party_id: int,
    entry_date: date,
    debit: Decimal,
    credit: Decimal,
    ref_type: str,
    ref_id: int | None,
    note: str,
    user: User,
) -> PartyLedger:
    """Append one ledger row inside the caller's transaction (no commit).

    Exactly one of debit/credit must be > 0 and the other 0.
    """
    debit, credit = Decimal(debit), Decimal(credit)
    if party_type not in KINDS:
        raise AppError(400, "INVALID_LEDGER_ENTRY", f"Unknown party type: {party_type}")
    if not (debit.is_finite() and credit.is_finite()):
        raise AppError(400, "INVALID_LEDGER_ENTRY", "Amounts must be numbers")
    if debit < 0 or credit < 0:
        raise AppError(400, "INVALID_LEDGER_ENTRY", "Debit and credit cannot be negative")
    if (debit > 0) == (credit > 0):
        raise AppError(
            400, "INVALID_LEDGER_ENTRY", "A ledger entry needs exactly one of debit or credit"
        )
    if not _party_exists(db, party_type, party_id):
        raise AppError(404, "PARTY_NOT_FOUND", f"{party_type.capitalize()} not found")
    if debit != debit.quantize(Decimal("0.01")) or credit != credit.quantize(Decimal("0.01")):
        raise AppError(400, "INVALID_LEDGER_ENTRY", "Amounts can have at most 2 decimal places")

    entry = PartyLedger(
        party_type=party_type,
        party_id=party_id,
        entry_date=entry_date,
        debit=debit,
        credit=credit,
        ref_type=ref_type,
        ref_id=ref_id,
        note=note[:255],
        created_by=user.id,
    )
    db.add(entry)
    db.flush()
    return entry


def get_balance(db: Session, party_type: str, party_id: int, before: date | None = None) -> Decimal:
    """Current due (customer: debit - credit; supplier: credit - debit). With `before`,
    only entries dated strictly before that day."""
    stmt = select(func.coalesce(func.sum(_signed(party_type)), 0)).where(
        PartyLedger.party_type == party_type, PartyLedger.party_id == party_id
    )
    if before is not None:
        stmt = stmt.where(PartyLedger.entry_date < before)
    return Decimal(db.scalar(stmt) or 0).quantize(Decimal("0.01"))


def get_statement(
    db: Session,
    party_type: str,
    party_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
) -> StatementOut:
    kind = KINDS[party_type]
    party = get_party(db, kind, party_id)
    if date_from and date_to and date_from > date_to:
        raise AppError(400, "INVALID_RANGE", "The start date is after the end date")

    opening = get_balance(db, party_type, party_id, before=date_from) if date_from else ZERO
    stmt = (
        select(PartyLedger)
        .where(PartyLedger.party_type == party_type, PartyLedger.party_id == party_id)
        .order_by(PartyLedger.entry_date, PartyLedger.id)
    )
    if date_from:
        stmt = stmt.where(PartyLedger.entry_date >= date_from)
    if date_to:
        stmt = stmt.where(PartyLedger.entry_date <= date_to)

    sign = 1 if party_type == CUSTOMER else -1
    balance = opening
    total_debit = total_credit = ZERO
    entries: list[StatementEntry] = []
    for row in db.scalars(stmt):
        balance += sign * (row.debit - row.credit)
        total_debit += row.debit
        total_credit += row.credit
        entries.append(
            StatementEntry(
                id=row.id,
                entry_date=row.entry_date,
                ref_type=row.ref_type,
                ref_id=row.ref_id,
                note=row.note,
                debit=row.debit,
                credit=row.credit,
                balance=balance,
            )
        )
    return StatementOut(
        party_type=party_type,  # type: ignore[arg-type]
        party=StatementParty(
            id=party.id,
            code=party.code,
            name=party.name,
            mobile=party.mobile,
            address=party.address,
        ),
        date_from=date_from,
        date_to=date_to,
        opening_balance=opening,
        entries=entries,
        total_debit=total_debit,
        total_credit=total_credit,
        closing_balance=balance,
    )


def _has_transactions(db: Session, party_type: str, party_ids: list[int]) -> set[int]:
    if not party_ids:
        return set()
    return set(
        db.scalars(
            select(PartyLedger.party_id)
            .where(
                PartyLedger.party_type == party_type,
                PartyLedger.party_id.in_(party_ids),
                PartyLedger.ref_type.not_in(OPENING_REF_TYPES),
            )
            .distinct()
        )
    )


def _dues(db: Session, kind: PartyKind, party_ids: list[int]) -> dict[int, Decimal]:
    if not party_ids:
        return {}
    view = kind.due_view
    id_col = view.c[kind.due_view_id]
    return dict(db.execute(select(id_col, view.c.due).where(id_col.in_(party_ids))).all())


# =========================================================================================
# Customers / suppliers CRUD
# =========================================================================================


def _out(party: Customer | Supplier, due: Decimal, has_transactions: bool) -> PartyOut:
    return PartyOut(
        id=party.id,
        code=party.code,
        name=party.name,
        contact_person=party.contact_person,
        mobile=party.mobile,
        email=party.email,
        address=party.address,
        opening_due=party.opening_due,
        notes=party.notes,
        is_active=party.is_active,
        due=due,
        has_transactions=has_transactions,
        created_at=party.created_at,
    )


def party_out(db: Session, kind: PartyKind, party: Customer | Supplier) -> PartyOut:
    return _out(
        party,
        get_balance(db, kind.party_type, party.id),
        party.id in _has_transactions(db, kind.party_type, [party.id]),
    )


def get_party(db: Session, kind: PartyKind, party_id: int) -> Customer | Supplier:
    party = db.get(kind.model, party_id)
    if party is None:
        raise AppError(404, f"{kind.party_type.upper()}_NOT_FOUND", f"{kind.label} not found")
    return party


def list_parties(
    db: Session, kind: PartyKind, params: PageParams, is_active: bool | None
) -> dict[str, Any]:
    model = kind.model
    stmt = select(model).order_by(model.name, model.id)
    if params.search:
        stmt = stmt.where(
            or_(
                *(
                    col.contains(params.search, autoescape=True)
                    for col in (model.name, model.code, model.mobile, model.contact_person)
                )
            )
        )
    if is_active is not None:
        stmt = stmt.where(model.is_active.is_(is_active))
    page = paginate(db, stmt, params)
    ids = [p.id for p in page["items"]]
    dues = _dues(db, kind, ids)
    busy = _has_transactions(db, kind.party_type, ids)
    page["items"] = [_out(p, dues.get(p.id, ZERO), p.id in busy) for p in page["items"]]
    return page


def _post_opening(
    db: Session,
    kind: PartyKind,
    party: Customer | Supplier,
    amount: Decimal,
    user: User,
    reversal: bool = False,
) -> None:
    """Opening due goes on the due side; its reversal on the other side."""
    on_due_side = not reversal
    debit_side = (kind.due_side == "debit") == on_due_side
    post_party_entry(
        db,
        kind.party_type,
        party.id,
        today(),
        amount if debit_side else ZERO,
        ZERO if debit_side else amount,
        OPENING_REVERSAL if reversal else OPENING,
        party.id,
        "Reversal of previous opening balance" if reversal else "Opening balance",
        user,
    )


_FIELDS = ["code", "name", "contact_person", "mobile", "email", "address", "opening_due", "notes"]


def _values(data: PartyIn) -> dict[str, Any]:
    values = data.model_dump()
    values["mobile"] = values["mobile"] or ""
    values["email"] = values["email"] or ""
    return values


def _check_code(db: Session, kind: PartyKind, code: str, exclude_id: int | None) -> None:
    stmt = select(kind.model.id).where(kind.model.code == code)
    if exclude_id is not None:
        stmt = stmt.where(kind.model.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise AppError(409, "CODE_TAKEN", f"{kind.label} code '{code}' is already in use")


def _commit(db: Session, kind: PartyKind) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(409, "CODE_TAKEN", f"{kind.label} code is already in use") from exc


def create_party(
    db: Session, actor: User, kind: PartyKind, data: PartyIn, request: Request | None = None
) -> PartyOut:
    """Create the party and, if opening_due > 0, its OPENING ledger entry, in one transaction."""
    values = _values(data)
    if data.code:
        _check_code(db, kind, data.code, None)
    else:
        values["code"] = next_free_code(db, kind.code_sequence, kind.model.code)
    party = kind.model(**values, is_active=True)
    db.add(party)
    db.flush()
    if data.opening_due > 0:
        _post_opening(db, kind, party, data.opening_due, actor)
    log_audit(
        db,
        actor,
        "create",
        kind.party_type,
        party.id,
        f"Created {kind.party_type} {party.code} {party.name}",
        new=values,
        request=request,
    )
    _commit(db, kind)
    db.refresh(party)
    return party_out(db, kind, party)


def update_party(
    db: Session,
    actor: User,
    kind: PartyKind,
    party_id: int,
    data: PartyIn,
    request: Request | None = None,
) -> PartyOut:
    party = get_party(db, kind, party_id)
    values = _values(data)
    values["code"] = data.code or party.code
    _check_code(db, kind, values["code"], party.id)

    if values["opening_due"] != party.opening_due:
        if party.id in _has_transactions(db, kind.party_type, [party.id]):
            raise AppError(
                400,
                "OPENING_LOCKED",
                "The opening due can't be changed after other transactions have been "
                "recorded for this party. Record an adjustment instead.",
            )
        # Ledger is append-only: reverse the old opening, then post the new one.
        if party.opening_due > 0:
            _post_opening(db, kind, party, party.opening_due, actor, reversal=True)
        if values["opening_due"] > 0:
            _post_opening(db, kind, party, values["opening_due"], actor)

    old = {f: getattr(party, f) for f in _FIELDS}
    for field in _FIELDS:
        setattr(party, field, values[field])
    changed = [f for f in _FIELDS if old[f] != values[f]]
    if changed:
        log_audit(
            db,
            actor,
            "update",
            kind.party_type,
            party.id,
            f"Updated {kind.party_type} {party.code}",
            old={f: old[f] for f in changed},
            new={f: values[f] for f in changed},
            request=request,
        )
    _commit(db, kind)
    return party_out(db, kind, party)


def set_party_active(
    db: Session,
    actor: User,
    kind: PartyKind,
    party_id: int,
    active: bool,
    request: Request | None = None,
) -> PartyOut:
    party = get_party(db, kind, party_id)
    if party.is_active != active:
        party.is_active = active
        action = "activate" if active else "deactivate"
        log_audit(
            db,
            actor,
            action,
            kind.party_type,
            party.id,
            f"{action.capitalize()}d {kind.party_type} {party.code}",
            old={"is_active": not active},
            new={"is_active": active},
            request=request,
        )
        db.commit()
    return party_out(db, kind, party)


def total_due(db: Session, kind: PartyKind) -> Decimal:
    """Sum of positive dues (dashboard: Customer Due / Supplier Due)."""
    view = kind.due_view
    total = db.scalar(
        select(func.coalesce(func.sum(case((view.c.due > 0, view.c.due), else_=0)), 0))
    )
    return Decimal(total or 0).quantize(Decimal("0.01"))
