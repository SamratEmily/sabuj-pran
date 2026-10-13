"""Money: accounts, ledger engine, vouchers, transfers, reversals, invariants."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.dates import today
from app.core.errors import AppError
from app.modules.auth.models import AuditLog, User
from app.modules.master.models import ExpenseCategory, IncomeCategory
from app.modules.money import service as money
from app.modules.money.models import MoneyAccount, MoneyTransaction, MoneyTransfer
from app.modules.parties import service as parties
from app.modules.parties.models import CUSTOMER, SUPPLIER
from app.modules.parties.schemas import PartyIn
from tests.conftest import auth_headers

API = "/api/v1/money"
D = Decimal


@pytest.fixture
def env(db: Session, admin: User) -> dict[str, int]:
    accounts = dict(db.execute(select(MoneyAccount.name, MoneyAccount.id)).all())
    customer = parties.create_party(
        db, admin, parties.CUSTOMERS, PartyIn(name="Rahim Traders", opening_due=D("1000"))
    )
    supplier = parties.create_party(
        db, admin, parties.SUPPLIERS, PartyIn(name="Plastic Mills", opening_due=D("3000"))
    )
    exp = db.scalar(select(ExpenseCategory.id).where(ExpenseCategory.name == "Rent"))
    inc = db.scalar(select(IncomeCategory.id))
    assert exp and inc
    return {
        "cash": accounts["Cash in Hand"],
        "bank": accounts["City Bank"],
        "bkash": accounts["bKash"],
        "cust": customer.id,
        "sup": supplier.id,
        "exp": exp,
        "inc": inc,
    }


def balance(db: Session, account_id: int) -> Decimal:
    db.expire_all()
    account = db.get(MoneyAccount, account_id)
    assert account is not None
    return account.balance


def fund(db: Session, admin: User, account_id: int, amount: str) -> None:
    money.money_in(db, account_id, D(amount), "INCOME", "TEST", None, today(), admin)
    db.commit()


def assert_ledger_matches_balances(db: Session) -> None:
    db.expire_all()
    for account in db.scalars(select(MoneyAccount)):
        assert money.ledger_balance(db, account.id) == account.balance >= 0
        last = db.scalar(
            select(MoneyTransaction.balance_after)
            .where(MoneyTransaction.account_id == account.id)
            .order_by(MoneyTransaction.id.desc())
            .limit(1)
        )
        assert last is None or last == account.balance
    view = dict(db.execute(text("SELECT account_id, balance FROM v_cash_position")).all())
    assert view == {a.id: a.balance for a in db.scalars(select(MoneyAccount))}


# --- accounts --------------------------------------------------------------------------


def test_opening_balance_posts_one_opening_row(
    client: TestClient, db: Session, admin: User
) -> None:
    h = auth_headers(admin)
    res = client.post(
        f"{API}/accounts",
        headers=h,
        json={"name": "Dutch-Bangla Bank", "account_type": "bank", "opening_balance": "5000.50"},
    )
    assert res.status_code == 201, res.text
    account = res.json()
    assert (account["balance"], account["opening_balance"]) == ("5000.50", "5000.50")
    rows = db.scalars(
        select(MoneyTransaction).where(MoneyTransaction.account_id == account["id"])
    ).all()
    assert [(r.txn_type, r.direction, r.amount, r.balance_after) for r in rows] == [
        ("OPENING", "in", D("5000.50"), D("5000.50"))
    ]

    zero = client.post(
        f"{API}/accounts", headers=h, json={"name": "Petty Cash", "account_type": "cash"}
    )
    assert zero.json()["balance"] == "0.00"
    assert (
        db.scalar(
            select(func.count())
            .select_from(MoneyTransaction)
            .where(MoneyTransaction.account_id == zero.json()["id"])
        )
        == 0
    )

    dup = client.post(
        f"{API}/accounts", headers=h, json={"name": "City Bank", "account_type": "bank"}
    )
    assert dup.json()["code"] == "NAME_TAKEN"

    position = client.get(f"{API}/position", headers=h).json()
    assert position == {"cash": "0.00", "bank": "5000.50", "mfs": "0.00", "total": "5000.50"}


def test_account_with_balance_cannot_be_deactivated(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    fund(db, admin, env["cash"], "10")
    res = client.post(f"{API}/accounts/{env['cash']}/deactivate", headers=h)
    assert res.status_code == 400 and res.json()["code"] == "ACCOUNT_HAS_BALANCE"
    assert (
        client.post(f"{API}/accounts/{env['bkash']}/deactivate", headers=h).json()["is_active"]
        is False
    )
    blocked = client.post(
        f"{API}/expenses",
        headers=h,
        json={"expense_category_id": env["exp"], "account_id": env["bkash"], "amount": "1"},
    )
    assert blocked.json()["code"] == "INACTIVE_ACCOUNT"


# --- vouchers & party ledgers ----------------------------------------------------------


def test_collection_credits_customer_due(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    res = client.post(
        f"{API}/collections",
        headers=h,
        json={
            "customer_id": env["cust"],
            "account_id": env["cash"],
            "amount": "400",
            "reference_no": "MR-11",
        },
    )
    assert res.status_code == 201, res.text
    col = res.json()
    assert (col["number"], col["status"], col["party_due"]) == ("COL-000001", "posted", "600.00")
    assert balance(db, env["cash"]) == D("400.00")
    assert parties.get_balance(db, CUSTOMER, env["cust"]) == D("600.00")

    # more than the due is an advance: allowed, due goes negative
    advance = client.post(
        f"{API}/collections",
        headers=h,
        json={"customer_id": env["cust"], "account_id": env["bank"], "amount": "1000"},
    )
    assert advance.json()["party_due"] == "-400.00"

    with_invoice = client.post(
        f"{API}/collections",
        headers=h,
        json={
            "customer_id": env["cust"],
            "account_id": env["cash"],
            "amount": "1",
            "invoice_id": 5,
        },
    )
    assert with_invoice.json()["code"] == "INVOICE_NOT_FOUND"
    assert_ledger_matches_balances(db)


def test_supplier_payment_debits_supplier_due(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    fund(db, admin, env["bank"], "5000")
    res = client.post(
        f"{API}/supplier-payments",
        headers=h,
        json={"supplier_id": env["sup"], "account_id": env["bank"], "amount": "1200"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["number"] == "PAY-000001"
    assert parties.get_balance(db, SUPPLIER, env["sup"]) == D("1800.00")
    assert balance(db, env["bank"]) == D("3800.00")
    entry = parties.get_statement(db, SUPPLIER, env["sup"]).entries[-1]
    assert (entry.ref_type, entry.debit) == ("SUPPLIER_PAYMENT", D("1200.00"))


def test_negative_balance_blocked(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    fund(db, admin, env["cash"], "100")
    with pytest.raises(AppError) as err:
        money.money_out(db, env["cash"], D("100.01"), "EXPENSE", "TEST", None, today(), admin)
    assert err.value.code == "INSUFFICIENT_FUNDS"

    before = (
        db.scalar(select(func.count()).select_from(MoneyTransaction)),
        parties.get_balance(db, SUPPLIER, env["sup"]),
    )
    pay = client.post(
        f"{API}/supplier-payments",
        headers=h,
        json={"supplier_id": env["sup"], "account_id": env["cash"], "amount": "150"},
    )
    assert pay.status_code == 400 and pay.json()["code"] == "INSUFFICIENT_FUNDS"
    assert "Cash in Hand" in pay.json()["detail"]
    # nothing posted, not even the voucher (one transaction)
    after = (
        db.scalar(select(func.count()).select_from(MoneyTransaction)),
        parties.get_balance(db, SUPPLIER, env["sup"]),
    )
    assert after == before
    assert client.get(f"{API}/supplier-payments", headers=h).json()["total"] == 0

    ok = client.post(
        f"{API}/expenses",
        headers=h,
        json={
            "expense_category_id": env["exp"],
            "account_id": env["cash"],
            "amount": "100",
            "paid_to": "Landlord",
        },
    )
    assert ok.status_code == 201 and balance(db, env["cash"]) == D("0.00")


def test_expense_and_income(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    inc = client.post(
        f"{API}/incomes",
        headers=h,
        json={"income_category_id": env["inc"], "account_id": env["bkash"], "amount": "750.25"},
    )
    assert (inc.json()["number"], inc.json()["category_name"]) == ("INC-000001", "Other Income")
    exp = client.post(
        f"{API}/expenses",
        headers=h,
        json={
            "expense_category_id": env["exp"],
            "account_id": env["bkash"],
            "amount": "250.25",
            "paid_to": "Landlord",
            "notes": "October rent",
        },
    )
    assert (exp.json()["number"], exp.json()["paid_to"]) == ("EXP-000001", "Landlord")
    assert balance(db, env["bkash"]) == D("500.00")

    listed = client.get(
        f"{API}/expenses", headers=h, params={"category_id": env["exp"], "search": "Land"}
    ).json()
    assert [e["number"] for e in listed["items"]] == ["EXP-000001"]
    assert (
        client.get(
            f"{API}/expenses", headers=h, params={"from": "2000-01-01", "to": "2000-01-02"}
        ).json()["total"]
        == 0
    )


# --- transfers -------------------------------------------------------------------------


def test_transfer_moves_money_and_validates(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    fund(db, admin, env["bank"], "1000")
    res = client.post(
        f"{API}/transfers",
        headers=h,
        json={"from_account_id": env["bank"], "to_account_id": env["cash"], "amount": "300"},
    )
    assert res.status_code == 201
    assert (
        res.json()["number"],
        res.json()["from_account_name"],
        res.json()["to_account_name"],
    ) == ("MTR-000001", "City Bank", "Cash in Hand")
    assert (balance(db, env["bank"]), balance(db, env["cash"])) == (D("700.00"), D("300.00"))

    same = client.post(
        f"{API}/transfers",
        headers=h,
        json={"from_account_id": env["bank"], "to_account_id": env["bank"], "amount": "1"},
    )
    assert same.json()["code"] == "SAME_ACCOUNT"
    short = client.post(
        f"{API}/transfers",
        headers=h,
        json={"from_account_id": env["cash"], "to_account_id": env["bank"], "amount": "300.01"},
    )
    assert short.json()["code"] == "INSUFFICIENT_FUNDS"
    assert (balance(db, env["bank"]), balance(db, env["cash"])) == (D("700.00"), D("300.00"))


def test_transfer_rolls_back_when_the_in_leg_fails(
    db: Session, admin: User, env: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    fund(db, admin, env["bank"], "1000")
    rows_before = db.scalar(select(func.count()).select_from(MoneyTransaction))

    def boom(*args: object, **kwargs: object) -> None:
        raise AppError(500, "BOOM", "simulated failure after the OUT leg")

    monkeypatch.setattr(money, "money_in", boom)
    with pytest.raises(AppError, match="simulated"):
        money.create_transfer(
            db,
            admin,
            money.TransferIn(
                from_account_id=env["bank"], to_account_id=env["cash"], amount=D("400")
            ),
        )
    assert (balance(db, env["bank"]), balance(db, env["cash"])) == (D("1000.00"), D("0.00"))
    assert db.scalar(select(func.count()).select_from(MoneyTransaction)) == rows_before
    assert db.scalar(select(func.count()).select_from(MoneyTransfer)) == 0


# --- reversals -------------------------------------------------------------------------


def test_reversal_restores_balances_and_dues(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    fund(db, admin, env["bank"], "2000")
    col = client.post(
        f"{API}/collections",
        headers=h,
        json={"customer_id": env["cust"], "account_id": env["cash"], "amount": "400"},
    ).json()
    pay = client.post(
        f"{API}/supplier-payments",
        headers=h,
        json={"supplier_id": env["sup"], "account_id": env["bank"], "amount": "500"},
    ).json()
    trf = client.post(
        f"{API}/transfers",
        headers=h,
        json={"from_account_id": env["bank"], "to_account_id": env["bkash"], "amount": "600"},
    ).json()

    r1 = client.post(
        f"{API}/collections/{col['id']}/reverse", headers=h, json={"reason": "Bounced"}
    )
    assert r1.status_code == 200, r1.text
    assert (r1.json()["status"], r1.json()["reversal_reason"]) == ("reversed", "Bounced")
    assert balance(db, env["cash"]) == D("0.00")
    assert parties.get_balance(db, CUSTOMER, env["cust"]) == D("1000.00")

    client.post(f"{API}/supplier-payments/{pay['id']}/reverse", headers=h, json={})
    assert parties.get_balance(db, SUPPLIER, env["sup"]) == D("3000.00")
    client.post(f"{API}/transfers/{trf['id']}/reverse", headers=h, json={})
    assert (balance(db, env["bank"]), balance(db, env["bkash"])) == (D("2000.00"), D("0.00"))

    again = client.post(f"{API}/collections/{col['id']}/reverse", headers=h, json={})
    assert again.json()["code"] == "ALREADY_REVERSED"
    reversal_rows = db.scalar(
        select(func.count())
        .select_from(MoneyTransaction)
        .where(MoneyTransaction.reversal_of_id.is_not(None))
    )
    assert reversal_rows == 4  # collection 1 + payment 1 + transfer 2
    assert (
        db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "reverse"))
        == 3
    )
    assert_ledger_matches_balances(db)


def test_reversal_blocked_when_money_already_spent(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    col = client.post(
        f"{API}/collections",
        headers=h,
        json={"customer_id": env["cust"], "account_id": env["cash"], "amount": "400"},
    ).json()
    client.post(
        f"{API}/expenses",
        headers=h,
        json={"expense_category_id": env["exp"], "account_id": env["cash"], "amount": "300"},
    )
    res = client.post(f"{API}/collections/{col['id']}/reverse", headers=h, json={})
    assert res.json()["code"] == "INSUFFICIENT_FUNDS"
    assert client.get(f"{API}/collections/{col['id']}", headers=h).json()["status"] == "posted"
    assert parties.get_balance(db, CUSTOMER, env["cust"]) == D("600.00")


# --- ledger, invariants, permissions ---------------------------------------------------


def test_account_ledger_running_balance(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    for amount in ("100", "250", "50"):
        client.post(
            f"{API}/collections",
            headers=h,
            json={"customer_id": env["cust"], "account_id": env["cash"], "amount": amount},
        )
    client.post(
        f"{API}/expenses",
        headers=h,
        json={"expense_category_id": env["exp"], "account_id": env["cash"], "amount": "75"},
    )
    page1 = client.get(
        f"{API}/accounts/{env['cash']}/ledger", headers=h, params={"page_size": 2}
    ).json()
    page2 = client.get(
        f"{API}/accounts/{env['cash']}/ledger", headers=h, params={"page_size": 2, "page": 2}
    ).json()
    assert [r["running_balance"] for r in page1["items"] + page2["items"]] == [
        "100.00",
        "350.00",
        "400.00",
        "325.00",
    ]
    assert page1["closing_balance"] == "325.00" == f"{balance(db, env['cash']):.2f}"
    assert [r["money_out"] for r in page2["items"]] == ["0.00", "75.00"]


def test_ledger_sum_equals_balance_after_mixed_operations(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    fund(db, admin, env["bank"], "10000")
    ops = [
        ("collections", {"customer_id": env["cust"], "account_id": env["cash"], "amount": "700"}),
        (
            "supplier-payments",
            {"supplier_id": env["sup"], "account_id": env["bank"], "amount": "2500"},
        ),
        (
            "transfers",
            {"from_account_id": env["bank"], "to_account_id": env["bkash"], "amount": "1234.56"},
        ),
        (
            "expenses",
            {"expense_category_id": env["exp"], "account_id": env["bkash"], "amount": "34.56"},
        ),
        (
            "incomes",
            {"income_category_id": env["inc"], "account_id": env["cash"], "amount": "99.99"},
        ),
        (
            "transfers",
            {"from_account_id": env["cash"], "to_account_id": env["bank"], "amount": "799.99"},
        ),
        (
            "expenses",
            {"expense_category_id": env["exp"], "account_id": env["cash"], "amount": "1"},
        ),  # fails
    ]
    for path, body in ops:
        client.post(f"{API}/{path}", headers=h, json=body)
    pay_id = client.get(f"{API}/supplier-payments", headers=h).json()["items"][0]["id"]
    client.post(f"{API}/supplier-payments/{pay_id}/reverse", headers=h, json={})
    assert_ledger_matches_balances(db)
    assert (balance(db, env["cash"]), balance(db, env["bank"]), balance(db, env["bkash"])) == (
        D("0.00"),
        D("9565.43"),
        D("1200.00"),
    )


def test_money_ledger_is_append_only(db: Session, admin: User, env: dict[str, int]) -> None:
    fund(db, admin, env["cash"], "5")
    row_id = db.scalar(select(MoneyTransaction.id))
    for sql in (
        "UPDATE money_transactions SET amount = 1 WHERE id = :id",
        "DELETE FROM money_transactions WHERE id = :id",
    ):
        with pytest.raises(OperationalError, match="append-only"), db.begin_nested():
            db.execute(text(sql), {"id": row_id})


def test_permissions(client: TestClient, db: Session, admin: User, env: dict[str, int]) -> None:
    sales = db.scalar(select(User).where(User.username == "sales"))
    assert sales is not None
    hs = auth_headers(sales)
    col = client.post(
        f"{API}/collections",
        headers=hs,
        json={"customer_id": env["cust"], "account_id": env["cash"], "amount": "10"},
    )
    assert col.status_code == 201  # Sales can collect
    exp = client.post(
        f"{API}/expenses",
        headers=hs,
        json={"expense_category_id": env["exp"], "account_id": env["cash"], "amount": "1"},
    )
    assert exp.status_code == 403
    assert client.get(f"{API}/accounts", headers=hs).status_code == 403
    lookups = client.get("/api/v1/master/lookups", headers=hs).json()
    assert {a["name"] for a in lookups["money_accounts"]} >= {"Cash in Hand", "City Bank"}
