"""Negative paths through the HTTP API: every seeded role is refused what it lacks, and the
business rules refuse impossible postings without leaving anything behind."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.auth.models import Role, User
from app.modules.inventory.models import StockTransaction
from app.modules.master.models import ExpenseCategory, IncomeCategory, Product, Warehouse
from app.modules.money.models import MoneyAccount, MoneyTransaction
from app.modules.parties.models import PartyLedger
from tests.conftest import auth_headers

API = "/api/v1"
D = Decimal

# role user -> (method, path) it must be refused (403), each a permission the role lacks
FORBIDDEN = {
    "sales": [
        ("POST", "/purchase/orders"),
        ("POST", "/money/expenses"),
        ("GET", "/money/accounts"),
        ("POST", "/inventory/adjustments"),
        ("GET", "/suppliers"),
        ("GET", "/admin/users"),
        ("POST", "/employees/payroll"),
        ("POST", "/approvals/1/approve"),
    ],
    "store": [
        ("POST", "/sales/orders"),
        ("GET", "/sales/invoices"),
        ("POST", "/money/collections"),
        ("POST", "/money/supplier-payments"),
        ("GET", "/money/accounts"),
        ("GET", "/customers"),
        ("GET", "/admin/audit-logs"),
    ],
    "accounts": [
        ("POST", "/purchase/orders"),
        ("POST", "/sales/orders"),
        ("POST", "/inventory/adjustments"),
        ("POST", "/sales/orders/1/deliver"),
        ("GET", "/admin/users"),
        ("PUT", "/employees/attendance"),
        ("POST", "/approvals/1/approve"),
    ],
    "owner": [  # views everything, changes nothing (except approving)
        ("POST", "/purchase/orders"),
        ("POST", "/money/expenses"),
        ("POST", "/sales/orders"),
        ("POST", "/customers"),
        ("PUT", "/admin/company-settings"),
        ("POST", "/approvals/rules"),
        ("POST", "/employees/payroll"),
    ],
}


@pytest.mark.parametrize(
    ("username", "method", "path"),
    [(u, m, p) for u, calls in FORBIDDEN.items() for m, p in calls],
)
def test_role_is_refused_what_it_lacks(
    client: TestClient, db: Session, admin: User, username: str, method: str, path: str
) -> None:
    user = db.scalar(select(User).where(User.username == username))
    assert user is not None
    res = client.request(method, f"{API}{path}", headers=auth_headers(user), json={})
    assert res.status_code == 403, f"{username} {method} {path}: {res.status_code} {res.text}"
    assert res.json()["code"] == "PERMISSION_DENIED"


def test_roles_can_do_their_own_work(client: TestClient, db: Session, admin: User) -> None:
    """Sanity check for the matrix above: the same roles are allowed their own screens."""
    allowed = {
        "sales": [("GET", "/sales/orders"), ("GET", "/customers"), ("GET", "/inventory/stock")],
        "store": [("GET", "/purchase/orders"), ("GET", "/suppliers"), ("GET", "/inventory/stock")],
        "accounts": [("GET", "/money/accounts"), ("GET", "/money/expenses")],
        "owner": [("GET", "/money/accounts"), ("GET", "/sales/invoices"), ("GET", "/admin/users")],
    }
    for username, calls in allowed.items():
        user = db.scalar(select(User).where(User.username == username))
        assert user is not None
        for method, path in calls:
            res = client.request(method, f"{API}{path}", headers=auth_headers(user))
            assert res.status_code == 200, f"{username} {method} {path}: {res.text}"


def test_unauthenticated_is_401(client: TestClient) -> None:
    assert client.get(f"{API}/sales/orders").status_code == 401
    assert client.get(f"{API}/dashboard/summary").status_code == 401


# --- business rules --------------------------------------------------------------------


@pytest.fixture
def env(client: TestClient, db: Session, admin: User) -> dict:
    h = auth_headers(admin)
    products = dict(db.execute(select(Product.code, Product.id)).all())
    wh = db.scalar(select(Warehouse.id).where(Warehouse.code == "MAIN"))
    accounts = dict(db.execute(select(MoneyAccount.name, MoneyAccount.id)).all())
    rent = db.scalar(select(ExpenseCategory.id).where(ExpenseCategory.name == "Rent"))
    sup = client.post(f"{API}/suppliers", headers=h, json={"name": "Meghna"}).json()
    cust = client.post(f"{API}/customers", headers=h, json={"name": "Rahim"}).json()
    return {
        "h": h,
        "p1": products["P-0001"],
        "wh": wh,
        "cash": accounts["Cash in Hand"],
        "bank": accounts["City Bank"],
        "rent": rent,
        "income": db.scalar(select(IncomeCategory.id)),
        "sup": sup["id"],
        "cust": cust["id"],
    }


def counts(db: Session) -> tuple[int, int, int]:
    db.expire_all()
    return tuple(  # type: ignore[return-value]
        db.scalar(select(func.count()).select_from(m)) or 0
        for m in (StockTransaction, MoneyTransaction, PartyLedger)
    )


def post(client: TestClient, env: dict, path: str, body: dict) -> dict:
    res = client.post(f"{API}{path}", headers=env["h"], json=body)
    assert res.status_code < 300, res.text
    return res.json()


def refused(client: TestClient, env: dict, path: str, body: dict, code: str) -> None:
    res = client.post(f"{API}{path}", headers=env["h"], json=body)
    assert res.status_code == 400, f"{path}: {res.status_code} {res.text}"
    assert res.json()["code"] == code, res.text


def approved_po(client: TestClient, env: dict, qty: str = "10") -> dict:
    po = post(
        client,
        env,
        "/purchase/orders",
        {
            "supplier_id": env["sup"],
            "warehouse_id": env["wh"],
            "items": [{"product_id": env["p1"], "qty": qty, "unit_cost": "100"}],
        },
    )
    return post(client, env, f"/purchase/orders/{po['id']}/approve", {})


def confirmed_so(client: TestClient, env: dict, qty: str) -> dict:
    so = post(
        client,
        env,
        "/sales/orders",
        {
            "customer_id": env["cust"],
            "warehouse_id": env["wh"],
            "items": [{"product_id": env["p1"], "qty": qty, "unit_price": "150"}],
        },
    )
    return post(client, env, f"/sales/orders/{so['id']}/confirm", {})


def test_over_receipt(client: TestClient, db: Session, env: dict) -> None:
    po = approved_po(client, env, "10")
    before = counts(db)
    body = {"items": [{"po_item_id": po["items"][0]["id"], "qty": "10.001"}]}
    refused(client, env, f"/purchase/orders/{po['id']}/receive", body, "OVER_RECEIPT")
    assert counts(db) == before


def test_insufficient_stock_and_over_delivery(client: TestClient, db: Session, env: dict) -> None:
    so = confirmed_so(client, env, "5")
    line = so["items"][0]["id"]
    before = counts(db)
    # nothing in stock yet
    refused(
        client, env, f"/sales/orders/{so['id']}/deliver",
        {"items": [{"so_item_id": line, "qty": "1"}]}, "INSUFFICIENT_STOCK",
    )  # fmt: skip
    refused(
        client, env, "/inventory/transfers",
        {"from_warehouse_id": env["wh"], "to_warehouse_id": env["wh"],
         "items": [{"product_id": env["p1"], "qty": "1"}]}, "SAME_WAREHOUSE",
    )  # fmt: skip
    adj = post(
        client,
        env,
        "/inventory/adjustments",
        {
            "warehouse_id": env["wh"],
            "reason": "Write-off",
            "items": [{"product_id": env["p1"], "direction": "decrease", "qty": "1"}],
        },
    )
    refused(client, env, f"/inventory/adjustments/{adj['id']}/post", {}, "INSUFFICIENT_STOCK")
    assert counts(db) == before

    # receive 3, then delivering 4 is short of stock and 6 is more than ordered
    po = approved_po(client, env, "3")
    post(
        client,
        env,
        f"/purchase/orders/{po['id']}/receive",
        {"items": [{"po_item_id": po["items"][0]["id"], "qty": "3"}]},
    )
    before = counts(db)
    refused(
        client, env, f"/sales/orders/{so['id']}/deliver",
        {"items": [{"so_item_id": line, "qty": "4"}]}, "INSUFFICIENT_STOCK",
    )  # fmt: skip
    refused(
        client, env, f"/sales/orders/{so['id']}/deliver",
        {"items": [{"so_item_id": line, "qty": "6"}]}, "OVER_DELIVERY",
    )  # fmt: skip
    assert counts(db) == before
    detail = client.get(f"{API}/sales/orders/{so['id']}", headers=env["h"]).json()
    assert (detail["status"], detail["items"][0]["qty_delivered"]) == ("confirmed", "0.000")


def test_negative_money_balance_is_refused(client: TestClient, db: Session, env: dict) -> None:
    before = counts(db)
    refused(
        client, env, "/money/expenses",
        {"expense_category_id": env["rent"], "account_id": env["cash"], "amount": "0.01"},
        "INSUFFICIENT_FUNDS",
    )  # fmt: skip
    refused(
        client, env, "/money/supplier-payments",
        {"supplier_id": env["sup"], "account_id": env["bank"], "amount": "100"},
        "INSUFFICIENT_FUNDS",
    )  # fmt: skip
    refused(
        client, env, "/money/transfers",
        {"from_account_id": env["cash"], "to_account_id": env["bank"], "amount": "1"},
        "INSUFFICIENT_FUNDS",
    )  # fmt: skip
    assert counts(db) == before
    db.expire_all()
    assert all(a.balance == 0 for a in db.scalars(select(MoneyAccount)))
    # nothing half-saved either: no expense, payment or transfer vouchers exist
    for path in ("/money/expenses", "/money/supplier-payments", "/money/transfers"):
        assert client.get(f"{API}{path}", headers=env["h"]).json()["total"] == 0, path


def test_pending_approval_does_not_post(
    client: TestClient, db: Session, admin: User, env: dict
) -> None:
    owner_role = db.scalar(select(Role.id).where(Role.name == "Owner"))
    for document_type, amount in (("EXPENSE", "1000"), ("PURCHASE_ORDER", "500")):
        post(
            client,
            env,
            "/approvals/rules",
            {"document_type": document_type, "min_amount": amount, "approver_role_id": owner_role},
        )
    post(
        client, env, "/money/incomes",
        {"income_category_id": env["income"], "account_id": env["cash"], "amount": "5000"},
    )  # fmt: skip
    before = counts(db)
    exp = post(
        client,
        env,
        "/money/expenses",
        {"expense_category_id": env["rent"], "account_id": env["cash"], "amount": "2000"},
    )
    po = approved_po(client, env, "10")  # 1,000 >= 500: submitted for approval
    assert (exp["status"], po["status"]) == ("pending_approval", "pending_approval")
    refused(
        client, env, f"/purchase/orders/{po['id']}/receive",
        {"items": [{"po_item_id": po["items"][0]["id"], "qty": "1"}]}, "INVALID_STATUS",
    )  # fmt: skip
    assert counts(db) == before
    db.expire_all()
    cash = db.get(MoneyAccount, env["cash"])
    assert cash is not None and cash.balance == D("5000.00")
