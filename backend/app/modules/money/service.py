"""Money: accounts, the money ledger engine, and vouchers (collections, supplier payments,
expenses, income, transfers).

Engine functions (`money_in`, `money_out`, `reverse_ref`) run in the caller's transaction and
lock the account row FOR UPDATE; account balances never go below zero (INSUFFICIENT_FUNDS).
Every voucher posting/reversal is one transaction (`atomic`). Posted vouchers are never
edited: they are reversed with opposite ledger rows (money + party).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.dates import today
from app.core.db import atomic, utcnow
from app.core.errors import AppError
from app.core.numbering import next_document_number
from app.core.pagination import PageParams
from app.modules.approvals import models as approval_types
from app.modules.approvals import service as approvals
from app.modules.auth.models import User
from app.modules.master.models import ExpenseCategory, IncomeCategory, PaymentMethod
from app.modules.money.models import (
    BANK,
    CASH,
    COLLECTION,
    DRAFT,
    EXPENSE,
    IN,
    INCOME,
    MFS,
    OPENING,
    OUT,
    PENDING_APPROVAL,
    POSTED,
    REJECTED,
    REVERSED,
    SUPPLIER_PAYMENT,
    TRANSFER_IN,
    TRANSFER_OUT,
    CustomerCollection,
    Expense,
    Income,
    MoneyAccount,
    MoneyTransaction,
    MoneyTransfer,
    SupplierPayment,
)
from app.modules.money.schemas import (
    AccountCreateIn,
    AccountUpdateIn,
    TransferIn,
)
from app.modules.parties import service as parties
from app.modules.parties.models import CUSTOMER, SUPPLIER, Customer, Supplier
from app.modules.sales import payments as invoice_payments
from app.modules.sales.models import Invoice

Q2 = Decimal("0.01")
ZERO = Decimal("0.00")


def _amount(value: Any) -> Decimal:
    amount = Decimal(value)
    if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Q2):
        raise AppError(400, "INVALID_AMOUNT", "Amount must be more than 0 with at most 2 decimals")
    return amount


# =========================================================================================
# Engine
# =========================================================================================


def _lock_account(db: Session, account_id: int) -> MoneyAccount:
    account = db.scalar(
        select(MoneyAccount)
        .where(MoneyAccount.id == account_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if account is None:
        raise AppError(404, "ACCOUNT_NOT_FOUND", f"Money account {account_id} not found")
    return account


def _lock_accounts(db: Session, ids: Iterable[int]) -> dict[int, MoneyAccount]:
    """Lock several accounts in id order (deadlock-free)."""
    return {i: _lock_account(db, i) for i in sorted(set(ids))}


def _row(
    db: Session,
    account: MoneyAccount,
    direction: str,
    amount: Decimal,
    txn_type: str,
    ref_type: str,
    ref_id: int | None,
    txn_date: date,
    user: User,
    note: str,
    reversal_of_id: int | None,
) -> MoneyTransaction:
    row = MoneyTransaction(
        account_id=account.id,
        direction=direction,
        amount=amount,
        txn_type=txn_type,
        ref_type=ref_type,
        ref_id=ref_id,
        txn_date=txn_date,
        note=note[:255],
        balance_after=account.balance,
        reversal_of_id=reversal_of_id,
        created_by=user.id,
    )
    db.add(row)
    db.flush()
    return row


def money_in(
    db: Session,
    account_id: int,
    amount: Any,
    txn_type: str,
    ref_type: str,
    ref_id: int | None,
    txn_date: date,
    user: User,
    note: str = "",
    reversal_of_id: int | None = None,
) -> MoneyTransaction:
    amount = _amount(amount)
    account = _lock_account(db, account_id)
    account.balance += amount
    return _row(
        db, account, IN, amount, txn_type, ref_type, ref_id, txn_date, user, note, reversal_of_id
    )


def money_out(
    db: Session,
    account_id: int,
    amount: Any,
    txn_type: str,
    ref_type: str,
    ref_id: int | None,
    txn_date: date,
    user: User,
    note: str = "",
    reversal_of_id: int | None = None,
) -> MoneyTransaction:
    amount = _amount(amount)
    account = _lock_account(db, account_id)
    if account.balance < amount:
        raise AppError(
            400,
            "INSUFFICIENT_FUNDS",
            f"Insufficient funds in {account.name}: balance {account.balance:,.2f}, "
            f"needed {amount:,.2f}",
        )
    account.balance -= amount
    return _row(
        db, account, OUT, amount, txn_type, ref_type, ref_id, txn_date, user, note, reversal_of_id
    )


def reverse_ref(db: Session, ref_type: str, ref_id: int, user: User, note: str) -> int:
    """Post the opposite of every (not yet reversed) money row of a document. Accounts are
    locked in id order first. Returns the number of rows reversed."""
    rows = list(
        db.scalars(
            select(MoneyTransaction)
            .where(
                MoneyTransaction.ref_type == ref_type,
                MoneyTransaction.ref_id == ref_id,
                MoneyTransaction.reversal_of_id.is_(None),
            )
            .order_by(MoneyTransaction.id)
        )
    )
    reversed_ids = set(
        db.scalars(
            select(MoneyTransaction.reversal_of_id).where(
                MoneyTransaction.reversal_of_id.in_([r.id for r in rows])
            )
        )
    )
    rows = [r for r in rows if r.id not in reversed_ids]
    _lock_accounts(db, [r.account_id for r in rows])
    # Put money back into accounts first so a transfer reversal can't fail on ordering.
    for row in sorted(rows, key=lambda r: r.direction != OUT):
        fn = money_in if row.direction == OUT else money_out
        fn(
            db,
            row.account_id,
            row.amount,
            row.txn_type,
            ref_type,
            ref_id,
            today(),
            user,
            note,
            reversal_of_id=row.id,
        )
    return len(rows)


def ledger_balance(db: Session, account_id: int) -> Decimal:
    """SUM(in) - SUM(out) from the ledger (must equal money_accounts.balance)."""
    signed = func.sum(
        func.if_(
            MoneyTransaction.direction == IN, MoneyTransaction.amount, -MoneyTransaction.amount
        )
    )
    value = db.scalar(
        select(func.coalesce(signed, 0)).where(MoneyTransaction.account_id == account_id)
    )
    return Decimal(value or 0).quantize(Q2)


# =========================================================================================
# Accounts
# =========================================================================================


def get_account(db: Session, account_id: int) -> MoneyAccount:
    account = db.get(MoneyAccount, account_id)
    if account is None:
        raise AppError(404, "ACCOUNT_NOT_FOUND", "Money account not found")
    return account


def _active_account(db: Session, account_id: int) -> MoneyAccount:
    account = get_account(db, account_id)
    if not account.is_active:
        raise AppError(400, "INACTIVE_ACCOUNT", f"{account.name} is inactive")
    return account


def _accounts_with_transactions(db: Session, ids: list[int]) -> set[int]:
    if not ids:
        return set()
    return set(
        db.scalars(
            select(MoneyTransaction.account_id)
            .where(MoneyTransaction.account_id.in_(ids), MoneyTransaction.txn_type != OPENING)
            .distinct()
        )
    )


def account_out(db: Session, accounts: list[MoneyAccount]) -> list[dict[str, Any]]:
    methods = {m.id: m.name for m in db.scalars(select(PaymentMethod))}
    busy = _accounts_with_transactions(db, [a.id for a in accounts])
    return [
        {
            "id": a.id,
            "name": a.name,
            "account_type": a.account_type,
            "payment_method_id": a.payment_method_id,
            "payment_method_name": methods.get(a.payment_method_id),
            "account_number": a.account_number,
            "opening_balance": a.opening_balance,
            "balance": a.balance,
            "is_active": a.is_active,
            "has_transactions": a.id in busy,
        }
        for a in accounts
    ]


def list_accounts(
    db: Session, params: PageParams, is_active: bool | None, account_type: str | None
) -> dict[str, Any]:
    stmt = select(MoneyAccount).order_by(MoneyAccount.account_type, MoneyAccount.name)
    if is_active is not None:
        stmt = stmt.where(MoneyAccount.is_active.is_(is_active))
    if account_type:
        stmt = stmt.where(MoneyAccount.account_type == account_type)
    if params.search:
        stmt = stmt.where(
            or_(
                MoneyAccount.name.contains(params.search, autoescape=True),
                MoneyAccount.account_number.contains(params.search, autoescape=True),
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    accounts = list(db.scalars(stmt.limit(params.page_size).offset(params.offset)))
    return {
        "items": account_out(db, accounts),
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
    }


def _check_account_fields(db: Session, data: AccountUpdateIn, exclude_id: int | None) -> None:
    stmt = select(MoneyAccount.id).where(MoneyAccount.name == data.name)
    if exclude_id is not None:
        stmt = stmt.where(MoneyAccount.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise AppError(409, "NAME_TAKEN", f"An account named '{data.name}' already exists")
    if data.payment_method_id is not None and db.get(PaymentMethod, data.payment_method_id) is None:
        raise AppError(400, "INVALID_PAYMENT_METHOD", "Payment method does not exist")


def create_account(
    db: Session, user: User, data: AccountCreateIn, request: Request | None = None
) -> MoneyAccount:
    """Create an account; an opening balance is posted as an OPENING IN in the same txn."""
    with atomic(db):
        _check_account_fields(db, data, None)
        account = MoneyAccount(
            **data.model_dump(exclude={"opening_balance"}),
            opening_balance=data.opening_balance,
            balance=ZERO,
            is_active=True,
        )
        db.add(account)
        db.flush()
        if data.opening_balance > 0:
            money_in(
                db,
                account.id,
                data.opening_balance,
                OPENING,
                "MONEY_ACCOUNT",
                account.id,
                today(),
                user,
                "Opening balance",
            )
        log_audit(
            db,
            user,
            "create",
            "money_account",
            account.id,
            f"Created account {account.name}",
            new=data.model_dump(),
            request=request,
        )
    return account


def update_account(
    db: Session, user: User, account_id: int, data: AccountUpdateIn, request: Request | None = None
) -> MoneyAccount:
    with atomic(db):
        account = _lock_account(db, account_id)
        _check_account_fields(db, data, account.id)
        fields = list(AccountUpdateIn.model_fields)
        old = {f: getattr(account, f) for f in fields}
        new = data.model_dump()
        for f in fields:
            setattr(account, f, new[f])
        changed = [f for f in fields if old[f] != new[f]]
        if changed:
            log_audit(
                db,
                user,
                "update",
                "money_account",
                account.id,
                f"Updated account {account.name}",
                old={f: old[f] for f in changed},
                new={f: new[f] for f in changed},
                request=request,
            )
    return account


def set_account_active(
    db: Session, user: User, account_id: int, active: bool, request: Request | None = None
) -> MoneyAccount:
    with atomic(db):
        account = _lock_account(db, account_id)
        if account.is_active != active:
            if not active and account.balance != 0:
                raise AppError(
                    400,
                    "ACCOUNT_HAS_BALANCE",
                    f"{account.name} still holds {account.balance:,.2f}. Transfer it out first.",
                )
            account.is_active = active
            action = "activate" if active else "deactivate"
            log_audit(
                db,
                user,
                action,
                "money_account",
                account.id,
                f"{action.capitalize()}d account {account.name}",
                old={"is_active": not active},
                new={"is_active": active},
                request=request,
            )
    return account


def cash_position(db: Session) -> dict[str, Decimal]:
    totals = dict(
        db.execute(
            select(MoneyAccount.account_type, func.sum(MoneyAccount.balance)).group_by(
                MoneyAccount.account_type
            )
        ).all()
    )
    out = {t: Decimal(totals.get(t) or 0).quantize(Q2) for t in (CASH, BANK, MFS)}
    return out | {"total": sum(out.values(), ZERO)}


def account_ledger(
    db: Session,
    params: PageParams,
    account_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    account = get_account(db, account_id)
    T = MoneyTransaction
    signed = func.if_(T.direction == IN, T.amount, -T.amount)
    opening = ZERO
    if date_from:
        opening = Decimal(
            db.scalar(
                select(func.coalesce(func.sum(signed), 0)).where(
                    T.account_id == account_id, T.txn_date < date_from
                )
            )
            or 0
        )
    cond = [T.account_id == account_id]
    if date_from:
        cond.append(T.txn_date >= date_from)
    if date_to:
        cond.append(T.txn_date <= date_to)
    running = func.sum(signed).over(order_by=(T.txn_date, T.id), rows=(None, 0)).label("running")
    ranked = select(T.id.label("id"), running).where(*cond).subquery()
    total = db.scalar(select(func.count()).select_from(ranked)) or 0
    movement = Decimal(db.scalar(select(func.coalesce(func.sum(signed), 0)).where(*cond)) or 0)
    rows = db.execute(
        select(T, ranked.c.running)
        .join(ranked, ranked.c.id == T.id)
        .order_by(T.txn_date, T.id)
        .limit(params.page_size)
        .offset(params.offset)
    ).all()
    users = {u.id: u.full_name for u in db.scalars(select(User))} if rows else {}
    return {
        "items": [
            {
                "id": t.id,
                "txn_date": t.txn_date,
                "txn_type": t.txn_type,
                "direction": t.direction,
                "amount": t.amount,
                "money_in": t.amount if t.direction == IN else ZERO,
                "money_out": t.amount if t.direction == OUT else ZERO,
                "balance_after": t.balance_after,
                "running_balance": opening + Decimal(run),
                "ref_type": t.ref_type,
                "ref_id": t.ref_id,
                "note": t.note,
                "reversal_of_id": t.reversal_of_id,
                "created_by_name": users.get(t.created_by),
                "created_at": t.created_at,
            }
            for t, run in rows
        ],
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
        "account_id": account.id,
        "account_name": account.name,
        "opening_balance": opening,
        "closing_balance": opening + movement,
    }


# =========================================================================================
# Vouchers (collections, supplier payments, expenses, income)
# =========================================================================================


@dataclass(frozen=True)
class Kind:
    model: Any
    entity: str  # audit entity type / permission resource
    label: str
    sequence: str
    number_field: str
    date_field: str
    txn_type: str  # money ledger type
    direction: str  # IN or OUT
    party_type: str | None = None  # customer / supplier: ledger entry alongside the money
    party_field: str | None = None
    category_model: Any = None
    category_field: str | None = None
    approval_type: str | None = None  # document type in approval rules, when rules apply


COLLECTIONS = Kind(
    CustomerCollection,
    "collection",
    "Collection",
    "COL",
    "col_number",
    "collection_date",
    COLLECTION,
    IN,
    CUSTOMER,
    "customer_id",
)
SUPPLIER_PAYMENTS = Kind(
    SupplierPayment,
    "supplier_payment",
    "Supplier payment",
    "PAY",
    "pay_number",
    "payment_date",
    SUPPLIER_PAYMENT,
    OUT,
    SUPPLIER,
    "supplier_id",
    approval_type=approval_types.SUPPLIER_PAYMENT,
)
EXPENSES = Kind(
    Expense,
    "expense",
    "Expense",
    "EXP",
    "exp_number",
    "expense_date",
    EXPENSE,
    OUT,
    category_model=ExpenseCategory,
    category_field="expense_category_id",
    approval_type=approval_types.EXPENSE,
)
INCOMES = Kind(
    Income,
    "income",
    "Income",
    "INC",
    "inc_number",
    "income_date",
    INCOME,
    IN,
    category_model=IncomeCategory,
    category_field="income_category_id",
)
KINDS = {k.entity: k for k in (COLLECTIONS, SUPPLIER_PAYMENTS, EXPENSES, INCOMES)}

_PARTY_MODELS = {CUSTOMER: Customer, SUPPLIER: Supplier}


def _number(kind: Kind, voucher: Any) -> str:
    return getattr(voucher, kind.number_field)


def _lock_voucher(db: Session, kind: Kind, voucher_id: int) -> Any:
    voucher = db.scalar(
        select(kind.model)
        .where(kind.model.id == voucher_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if voucher is None:
        raise AppError(404, "NOT_FOUND", f"{kind.label} not found")
    return voucher


def _post_money(db: Session, kind: Kind, voucher: Any, user: User) -> None:
    """Money movement + party ledger entry for one voucher (caller's transaction)."""
    when = getattr(voucher, kind.date_field)
    number = _number(kind, voucher)
    fn = money_in if kind.direction == IN else money_out
    fn(
        db,
        voucher.account_id,
        voucher.amount,
        kind.txn_type,
        kind.txn_type,
        voucher.id,
        when,
        user,
        number,
    )
    if kind.party_type:
        # Money IN from a customer = customer credit; money OUT to a supplier = supplier debit.
        debit, credit = (ZERO, voucher.amount) if kind.direction == IN else (voucher.amount, ZERO)
        parties.post_party_entry(
            db,
            kind.party_type,
            getattr(voucher, kind.party_field),
            when,
            debit,
            credit,
            kind.txn_type,
            voucher.id,
            number,
            user,
        )
    voucher.status = POSTED
    voucher.posted_at = utcnow()


def create_voucher(
    db: Session, user: User, kind: Kind, data: Any, request: Request | None = None
) -> Any:
    """Create and (unless an approval rule applies) post a voucher, in one transaction."""
    with atomic(db):
        values = data.model_dump()
        _active_account(db, values["account_id"])
        if kind.party_type:
            party = db.get(_PARTY_MODELS[kind.party_type], values[kind.party_field])
            if party is None or not party.is_active:
                raise AppError(
                    400, f"INVALID_{kind.party_type.upper()}", f"Choose an active {kind.party_type}"
                )
        if kind is COLLECTIONS and values.get("invoice_id") is not None:
            # Same customer, capped at the invoice's outstanding amount; adds to paid_amount.
            invoice_payments.apply_payment(
                db, values["invoice_id"], values["customer_id"], values["amount"]
            )
        if kind.category_model is not None:
            category = db.get(kind.category_model, values[kind.category_field])
            if category is None or not category.is_active:
                raise AppError(400, "INVALID_CATEGORY", "Choose an active category")
        values[kind.date_field] = values[kind.date_field] or today()
        voucher = kind.model(**values, status=DRAFT, created_by=user.id)
        setattr(voucher, kind.number_field, next_document_number(db, kind.sequence))
        db.add(voucher)
        db.flush()
        log_audit(
            db,
            user,
            "create",
            kind.entity,
            voucher.id,
            f"Created {kind.label.lower()} {_number(kind, voucher)}: {voucher.amount:,.2f}",
            new=values,
            request=request,
        )
        if kind.approval_type and approvals.maybe_require_approval(
            db,
            kind.approval_type,
            voucher.id,
            _number(kind, voucher),
            voucher.amount,
            user,
            request,
        ):
            voucher.status = PENDING_APPROVAL  # nothing is posted until approved
        else:
            _finalize(db, kind, voucher, user, request)
    return voucher


def _finalize(db: Session, kind: Kind, voucher: Any, user: User, request: Request | None) -> None:
    _post_money(db, kind, voucher, user)
    log_audit(
        db,
        user,
        "post",
        kind.entity,
        voucher.id,
        f"Posted {kind.label.lower()} {_number(kind, voucher)}",
        request=request,
    )


def finalize_voucher(
    db: Session,
    kind: Kind,
    voucher_id: int,
    user: User,
    request: Request | None = None,
    allowed: tuple[str, ...] = (PENDING_APPROVAL,),
) -> Any:
    """Post a pending voucher. The approvals module calls this after approval."""
    with atomic(db):
        voucher = _lock_voucher(db, kind, voucher_id)
        if voucher.status not in allowed:
            raise AppError(
                400,
                "INVALID_STATUS",
                f"{_number(kind, voucher)} is {voucher.status.replace('_', ' ')}",
            )
        _finalize(db, kind, voucher, user, request)
    return voucher


def reject_voucher(
    db: Session,
    kind: Kind,
    voucher_id: int,
    user: User,
    remark: str,
    request: Request | None = None,
) -> Any:
    """Approvals module: a pending voucher was rejected. Final; nothing was posted."""
    with atomic(db):
        voucher = _lock_voucher(db, kind, voucher_id)
        if voucher.status != PENDING_APPROVAL:
            raise AppError(
                400,
                "INVALID_STATUS",
                f"{_number(kind, voucher)} is {voucher.status.replace('_', ' ')}",
            )
        voucher.status = REJECTED
        log_audit(
            db,
            user,
            "reject",
            kind.entity,
            voucher.id,
            f"Rejected {_number(kind, voucher)}: {remark}",
            old={"status": PENDING_APPROVAL},
            new={"status": REJECTED},
            request=request,
        )
    return voucher


def reverse_voucher(
    db: Session,
    kind: Kind,
    voucher_id: int,
    user: User,
    reason: str = "",
    request: Request | None = None,
) -> Any:
    """Undo a posted voucher with opposite money (and party) ledger rows."""
    with atomic(db):
        voucher = _lock_voucher(db, kind, voucher_id)
        number = _number(kind, voucher)
        if voucher.status == REVERSED:
            raise AppError(400, "ALREADY_REVERSED", f"{number} is already reversed")
        if voucher.status != POSTED:
            raise AppError(400, "INVALID_STATUS", f"{number} is not posted")
        note = f"Reversal of {number}" + (f": {reason}" if reason else "")
        reverse_ref(db, kind.txn_type, voucher.id, user, note)
        if kind.party_type:
            # Opposite of the original party entry.
            debit, credit = (
                (voucher.amount, ZERO) if kind.direction == IN else (ZERO, voucher.amount)
            )
            parties.post_party_entry(
                db,
                kind.party_type,
                getattr(voucher, kind.party_field),
                today(),
                debit,
                credit,
                f"{kind.txn_type}_REVERSAL",
                voucher.id,
                note,
                user,
            )
        if kind is COLLECTIONS and voucher.invoice_id is not None:
            invoice_payments.remove_payment(db, voucher.invoice_id, voucher.amount)
        voucher.status = REVERSED
        voucher.reversed_by = user.id
        voucher.reversed_at = utcnow()
        voucher.reversal_reason = reason
        log_audit(
            db,
            user,
            "reverse",
            kind.entity,
            voucher.id,
            f"Reversed {number}",
            old={"status": POSTED},
            new={"status": REVERSED, "reason": reason},
            request=request,
        )
    return voucher


for _kind in (EXPENSES, SUPPLIER_PAYMENTS):
    approvals.register(
        _kind.approval_type,  # type: ignore[arg-type]
        lambda db, doc_id, user, kind=_kind: finalize_voucher(db, kind, doc_id, user),
        lambda db, doc_id, user, remark, kind=_kind: reject_voucher(db, kind, doc_id, user, remark),
    )


# =========================================================================================
# Transfers
# =========================================================================================


def create_transfer(
    db: Session, user: User, data: TransferIn, request: Request | None = None
) -> MoneyTransfer:
    """OUT from the source + IN to the destination, atomically."""
    if data.from_account_id == data.to_account_id:
        raise AppError(400, "SAME_ACCOUNT", "Choose two different accounts")
    with atomic(db):
        _active_account(db, data.from_account_id)
        _active_account(db, data.to_account_id)
        transfer = MoneyTransfer(
            mtr_number=next_document_number(db, "MTR"),
            from_account_id=data.from_account_id,
            to_account_id=data.to_account_id,
            amount=data.amount,
            transfer_date=data.transfer_date or today(),
            notes=data.notes,
            status=POSTED,
            created_by=user.id,
        )
        db.add(transfer)
        db.flush()
        _lock_accounts(db, [data.from_account_id, data.to_account_id])
        money_out(
            db,
            transfer.from_account_id,
            transfer.amount,
            TRANSFER_OUT,
            "MONEY_TRANSFER",
            transfer.id,
            transfer.transfer_date,
            user,
            transfer.mtr_number,
        )
        money_in(
            db,
            transfer.to_account_id,
            transfer.amount,
            TRANSFER_IN,
            "MONEY_TRANSFER",
            transfer.id,
            transfer.transfer_date,
            user,
            transfer.mtr_number,
        )
        log_audit(
            db,
            user,
            "post",
            "money_transfer",
            transfer.id,
            f"Transfer {transfer.mtr_number}: {transfer.amount:,.2f}",
            new=data.model_dump(),
            request=request,
        )
    return transfer


def reverse_transfer(
    db: Session, transfer_id: int, user: User, reason: str = "", request: Request | None = None
) -> MoneyTransfer:
    with atomic(db):
        transfer = db.scalar(
            select(MoneyTransfer)
            .where(MoneyTransfer.id == transfer_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if transfer is None:
            raise AppError(404, "NOT_FOUND", "Transfer not found")
        if transfer.status == REVERSED:
            raise AppError(400, "ALREADY_REVERSED", f"{transfer.mtr_number} is already reversed")
        note = f"Reversal of {transfer.mtr_number}" + (f": {reason}" if reason else "")
        reverse_ref(db, "MONEY_TRANSFER", transfer.id, user, note)
        transfer.status = REVERSED
        transfer.reversed_by = user.id
        transfer.reversed_at = utcnow()
        transfer.reversal_reason = reason
        log_audit(
            db,
            user,
            "reverse",
            "money_transfer",
            transfer.id,
            f"Reversed {transfer.mtr_number}",
            new={"reason": reason},
            request=request,
        )
    return transfer


# =========================================================================================
# Read side
# =========================================================================================


def _names(db: Session, model: Any, ids: Iterable[int | None]) -> dict[int, Any]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    return {o.id: o for o in db.scalars(select(model).where(model.id.in_(wanted)))}


def vouchers_out(
    db: Session, kind: Kind | None, vouchers: list[Any], with_due: bool = False
) -> list[dict[str, Any]]:
    """Shape vouchers (or transfers when kind is None) as VoucherOut dicts."""
    is_transfer = kind is None
    account_ids = (
        [a for v in vouchers for a in (v.from_account_id, v.to_account_id)]
        if is_transfer
        else [v.account_id for v in vouchers]
    )
    accounts = _names(db, MoneyAccount, account_ids)
    users = _names(db, User, [u for v in vouchers for u in (v.created_by, v.reversed_by)])
    parties_by_id = (
        _names(db, _PARTY_MODELS[kind.party_type], [getattr(v, kind.party_field) for v in vouchers])
        if kind and kind.party_type
        else {}
    )
    invoices = _names(db, Invoice, [v.invoice_id for v in vouchers]) if kind is COLLECTIONS else {}
    categories = (
        _names(db, kind.category_model, [getattr(v, kind.category_field) for v in vouchers])
        if kind and kind.category_model is not None
        else {}
    )
    out = []
    for v in vouchers:
        item: dict[str, Any] = {
            "id": v.id,
            "amount": v.amount,
            "status": v.status,
            "notes": v.notes,
            "created_by_name": users[v.created_by].full_name,
            "created_at": v.created_at,
            "reversed_by_name": users[v.reversed_by].full_name if v.reversed_by else None,
            "reversed_at": v.reversed_at,
            "reversal_reason": v.reversal_reason,
        }
        if is_transfer:
            item |= {
                "number": v.mtr_number,
                "voucher_date": v.transfer_date,
                "account_id": None,
                "account_name": None,
                "from_account_id": v.from_account_id,
                "from_account_name": accounts[v.from_account_id].name,
                "to_account_id": v.to_account_id,
                "to_account_name": accounts[v.to_account_id].name,
            }
        else:
            assert kind is not None
            item |= {
                "number": _number(kind, v),
                "voucher_date": getattr(v, kind.date_field),
                "account_id": v.account_id,
                "account_name": accounts[v.account_id].name,
            }
            if kind.party_type:
                party = parties_by_id[getattr(v, kind.party_field)]
                item |= {
                    "party_id": party.id,
                    "party_code": party.code,
                    "party_name": party.name,
                    "reference_no": v.reference_no,
                }
                if with_due:
                    item["party_due"] = parties.get_balance(db, kind.party_type, party.id)
                if kind is COLLECTIONS:
                    item["invoice_id"] = v.invoice_id
                    item["invoice_number"] = (
                        invoices[v.invoice_id].inv_number if v.invoice_id else None
                    )
            if kind.category_model is not None:
                category = categories[getattr(v, kind.category_field)]
                item |= {"category_id": category.id, "category_name": category.name}
                if kind is EXPENSES:
                    item["paid_to"] = v.paid_to
        out.append(item)
    return out


def list_vouchers(
    db: Session,
    kind: Kind | None,
    params: PageParams,
    date_from: date | None = None,
    date_to: date | None = None,
    account_id: int | None = None,
    party_id: int | None = None,
    category_id: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    model = kind.model if kind else MoneyTransfer
    date_col = getattr(model, kind.date_field if kind else "transfer_date")
    number_col = getattr(model, kind.number_field if kind else "mtr_number")
    stmt = select(model).order_by(date_col.desc(), model.id.desc())
    if date_from:
        stmt = stmt.where(date_col >= date_from)
    if date_to:
        stmt = stmt.where(date_col <= date_to)
    if account_id is not None:
        stmt = stmt.where(
            or_(model.from_account_id == account_id, model.to_account_id == account_id)
            if kind is None
            else model.account_id == account_id
        )
    if party_id is not None and kind and kind.party_field:
        stmt = stmt.where(getattr(model, kind.party_field) == party_id)
    if category_id is not None and kind and kind.category_field:
        stmt = stmt.where(getattr(model, kind.category_field) == category_id)
    if status:
        stmt = stmt.where(model.status == status)
    if params.search:
        conds = [number_col.contains(params.search, autoescape=True)]
        if kind and hasattr(model, "reference_no"):
            conds.append(model.reference_no.contains(params.search, autoescape=True))
        if kind is EXPENSES:
            conds.append(model.paid_to.contains(params.search, autoescape=True))
        stmt = stmt.where(or_(*conds))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    vouchers = list(db.scalars(stmt.limit(params.page_size).offset(params.offset)))
    return {
        "items": vouchers_out(db, kind, vouchers),
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
    }


def get_voucher(db: Session, kind: Kind | None, voucher_id: int) -> Any:
    model = kind.model if kind else MoneyTransfer
    voucher = db.get(model, voucher_id)
    if voucher is None:
        raise AppError(404, "NOT_FOUND", f"{kind.label if kind else 'Transfer'} not found")
    return voucher
