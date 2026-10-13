from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.core.deps import Allow, DbDep
from app.core.pagination import Page, PageParamsDep
from app.modules.money import service
from app.modules.money.schemas import (
    AccountCreateIn,
    AccountLedgerPage,
    AccountOut,
    AccountType,
    AccountUpdateIn,
    CollectionIn,
    ExpenseIn,
    IncomeIn,
    PositionOut,
    ReverseIn,
    SupplierPaymentIn,
    TransferIn,
    VoucherOut,
    VoucherStatus,
)
from app.modules.money.service import Kind

router = APIRouter(prefix="/money", tags=["money"])

DateFrom = Annotated[date | None, Query(alias="from")]
DateTo = Annotated[date | None, Query(alias="to")]


# --- accounts --------------------------------------------------------------------------


def _account(db: DbDep, account: Any) -> AccountOut:
    return AccountOut(**service.account_out(db, [account])[0])


@router.get("/accounts")
def list_accounts(
    db: DbDep,
    params: PageParamsDep,
    _: Allow("money_account.view"),
    is_active: bool | None = None,
    account_type: AccountType | None = None,
) -> Page[AccountOut]:
    return Page[AccountOut](**service.list_accounts(db, params, is_active, account_type))


@router.get("/position")
def position(db: DbDep, _: Allow("money_account.view")) -> PositionOut:
    return PositionOut(**service.cash_position(db))


@router.post("/accounts", status_code=201)
def create_account(
    data: AccountCreateIn, db: DbDep, user: Allow("money_account.create"), request: Request
) -> AccountOut:
    return _account(db, service.create_account(db, user, data, request))


@router.get("/accounts/{account_id}")
def get_account(account_id: int, db: DbDep, _: Allow("money_account.view")) -> AccountOut:
    return _account(db, service.get_account(db, account_id))


@router.put("/accounts/{account_id}")
def update_account(
    account_id: int,
    data: AccountUpdateIn,
    db: DbDep,
    user: Allow("money_account.edit"),
    request: Request,
) -> AccountOut:
    return _account(db, service.update_account(db, user, account_id, data, request))


@router.post("/accounts/{account_id}/deactivate")
def deactivate_account(
    account_id: int, db: DbDep, user: Allow("money_account.delete"), request: Request
) -> AccountOut:
    return _account(db, service.set_account_active(db, user, account_id, False, request))


@router.post("/accounts/{account_id}/activate")
def activate_account(
    account_id: int, db: DbDep, user: Allow("money_account.delete"), request: Request
) -> AccountOut:
    return _account(db, service.set_account_active(db, user, account_id, True, request))


@router.get("/accounts/{account_id}/ledger")
def account_ledger(
    account_id: int,
    db: DbDep,
    params: PageParamsDep,
    _: Allow("money_account.view"),
    date_from: DateFrom = None,
    date_to: DateTo = None,
) -> AccountLedgerPage:
    return AccountLedgerPage(**service.account_ledger(db, params, account_id, date_from, date_to))


# --- vouchers --------------------------------------------------------------------------


def _voucher_routes(path: str, kind: Kind | None, schema_in: type[BaseModel]) -> None:
    """list / create / detail / reverse for one voucher type (transfers when kind is None).
    Permissions: `<entity>.view|create`, reverse = `.delete`."""
    perm = kind.entity if kind else "money_transfer"

    @router.get(path, name=f"list_{perm}")
    def list_(
        db: DbDep,
        params: PageParamsDep,
        _: Allow(f"{perm}.view"),
        date_from: DateFrom = None,
        date_to: DateTo = None,
        account_id: int | None = None,
        party_id: int | None = None,
        category_id: int | None = None,
        status: VoucherStatus | None = None,
    ) -> Page[VoucherOut]:
        return Page[VoucherOut](
            **service.list_vouchers(
                db, kind, params, date_from, date_to, account_id, party_id, category_id, status
            )
        )

    @router.post(path, status_code=201, name=f"create_{perm}")
    def create(
        data: schema_in, db: DbDep, user: Allow(f"{perm}.create"), request: Request
    ) -> VoucherOut:
        voucher = (
            service.create_voucher(db, user, kind, data, request)
            if kind
            else service.create_transfer(db, user, data, request)
        )
        return VoucherOut(**service.vouchers_out(db, kind, [voucher], with_due=True)[0])

    @router.get(f"{path}/{{voucher_id}}", name=f"get_{perm}")
    def get(voucher_id: int, db: DbDep, _: Allow(f"{perm}.view")) -> VoucherOut:
        voucher = service.get_voucher(db, kind, voucher_id)
        return VoucherOut(**service.vouchers_out(db, kind, [voucher], with_due=True)[0])

    @router.post(f"{path}/{{voucher_id}}/reverse", name=f"reverse_{perm}")
    def reverse(
        voucher_id: int, data: ReverseIn, db: DbDep, user: Allow(f"{perm}.delete"), request: Request
    ) -> VoucherOut:
        voucher = (
            service.reverse_voucher(db, kind, voucher_id, user, data.reason, request)
            if kind
            else service.reverse_transfer(db, voucher_id, user, data.reason, request)
        )
        return VoucherOut(**service.vouchers_out(db, kind, [voucher], with_due=True)[0])


_voucher_routes("/collections", service.COLLECTIONS, CollectionIn)
_voucher_routes("/supplier-payments", service.SUPPLIER_PAYMENTS, SupplierPaymentIn)
_voucher_routes("/expenses", service.EXPENSES, ExpenseIn)
_voucher_routes("/incomes", service.INCOMES, IncomeIn)
_voucher_routes("/transfers", None, TransferIn)
