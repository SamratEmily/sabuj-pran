"""End-to-end business cycle through the HTTP API, each step done by the role that owns
it (seeded users), with the books checked after every step:

Supplier -> PO -> approve -> receive (twice) -> pay supplier -> quotation -> order ->
confirm -> reserve -> deliver with invoice -> collect partially -> collect the rest ->
expense -> dashboard.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import User
from app.modules.master.models import ExpenseCategory, IncomeCategory, Product, Warehouse
from app.modules.money.models import MoneyAccount
from tests.conftest import auth_headers

API = "/api/v1"


class Actor:
    """A logged-in seeded user calling the API."""

    def __init__(self, client: TestClient, user: User) -> None:
        self.client, self.headers, self.name = client, auth_headers(user), user.username

    def get(self, path: str, **params: object) -> dict:
        res = self.client.get(f"{API}{path}", headers=self.headers, params=params)
        assert res.status_code == 200, f"{self.name} GET {path}: {res.text}"
        return res.json()

    def post(self, path: str, body: dict | None = None, status: int | None = None) -> dict:
        res = self.client.post(f"{API}{path}", headers=self.headers, json=body or {})
        assert res.status_code == (status or res.status_code) and res.status_code < 300, (
            f"{self.name} POST {path}: {res.status_code} {res.text}"
        )
        return res.json()


@pytest.fixture
def actors(client: TestClient, db: Session, admin: User) -> dict[str, Actor]:
    users = {u.username: u for u in db.scalars(select(User))}
    return {name: Actor(client, users[name]) for name in ("store", "accounts", "sales", "owner")}


def test_full_business_cycle(db: Session, actors: dict[str, Actor]) -> None:
    store, accounts, sales, owner = (actors[k] for k in ("store", "accounts", "sales", "owner"))
    products = dict(db.execute(select(Product.code, Product.id)).all())
    p1, p2 = products["P-0001"], products["P-0002"]
    wh = db.scalar(select(Warehouse.id).where(Warehouse.code == "MAIN"))
    money_accounts = dict(db.execute(select(MoneyAccount.name, MoneyAccount.id)).all())
    cash, bank = money_accounts["Cash in Hand"], money_accounts["City Bank"]
    rent = db.scalar(select(ExpenseCategory.id).where(ExpenseCategory.name == "Rent"))
    other_income = db.scalar(select(IncomeCategory.id))

    # --- what the books say, read as the Owner (view-everything role) -------------------
    def stock(product_id: int) -> tuple[str, str, str, str]:
        rows = owner.get("/inventory/stock", product_id=product_id, warehouse_id=wh)["items"]
        if not rows:
            return ("0.000", "0.000", "0.000", "0.0000")
        r = rows[0]
        return (r["qty_on_hand"], r["qty_reserved"], r["qty_available"], r["avg_cost"])

    def supplier_due() -> str:
        return owner.get(f"/suppliers/{supplier['id']}")["due"]

    def customer_due() -> str:
        return owner.get(f"/customers/{customer['id']}")["due"]

    def balances() -> tuple[str, str]:
        rows = {a["id"]: a["balance"] for a in owner.get("/money/accounts")["items"]}
        return rows[cash], rows[bank]

    # 1. Store: supplier and purchase order (100 x P1 @50 + 40 x P2 @25, discount 100)
    supplier = store.post("/suppliers", {"name": "Meghna Polymers"}, status=201)
    po = store.post(
        "/purchase/orders",
        {
            "supplier_id": supplier["id"],
            "warehouse_id": wh,
            "discount": "100",
            "items": [
                {"product_id": p1, "qty": "100", "unit_cost": "50"},
                {"product_id": p2, "qty": "40", "unit_cost": "25"},
            ],
        },
        status=201,
    )
    assert (po["status"], po["total"]) == ("draft", "5900.00")

    # 2. Store: approve (no rule applies)
    assert store.post(f"/purchase/orders/{po['id']}/approve")["status"] == "approved"
    assert stock(p1) == ("0.000", "0.000", "0.000", "0.0000")
    assert supplier_due() == "0.00"

    # 3. Store: receive 60 x P1 + all P2 at PO cost, then the other 40 x P1 at 56
    lines = {i["product_id"]: i["id"] for i in po["items"]}
    grn1 = store.post(
        f"/purchase/orders/{po['id']}/receive",
        {"items": [{"po_item_id": lines[p1], "qty": "60"}, {"po_item_id": lines[p2], "qty": "40"}]},
        status=201,
    )
    # 4,000 gross, discount share 100 x 4,000 / 6,000 = 66.67
    assert (grn1["subtotal"], grn1["discount"], grn1["total"]) == ("4000.00", "66.67", "3933.33")
    assert stock(p1) == ("60.000", "0.000", "60.000", "50.0000")
    assert stock(p2) == ("40.000", "0.000", "40.000", "25.0000")
    assert supplier_due() == "3933.33"
    grn2 = store.post(
        f"/purchase/orders/{po['id']}/receive",
        {"items": [{"po_item_id": lines[p1], "qty": "40", "unit_cost": "56"}]},
        status=201,
    )
    # completing receipt takes the remaining discount 33.33
    assert (grn2["subtotal"], grn2["discount"], grn2["total"]) == ("2240.00", "33.33", "2206.67")
    # avg (60 x 50 + 40 x 56) / 100 = 52.40
    assert stock(p1) == ("100.000", "0.000", "100.000", "52.4000")
    assert owner.get(f"/purchase/orders/{po['id']}")["status"] == "received"
    assert supplier_due() == "6140.00"

    # 4. Accounts: other income funds the cash box, then pay the supplier 4,000
    accounts.post(
        "/money/incomes",
        {"income_category_id": other_income, "account_id": cash, "amount": "10000"},
        status=201,
    )
    assert balances() == ("10000.00", "0.00")
    accounts.post(
        "/money/supplier-payments",
        {"supplier_id": supplier["id"], "account_id": cash, "amount": "4000"},
        status=201,
    )
    assert balances() == ("6000.00", "0.00")
    assert supplier_due() == "2140.00"

    # 5. Sales: customer, quotation (30 x P1 @80 + 10 x P2 @40 = 2,800), convert, confirm
    customer = sales.post("/customers", {"name": "Rahim Traders"}, status=201)
    qt = sales.post(
        "/sales/quotations",
        {
            "customer_id": customer["id"],
            "items": [
                {"product_id": p1, "qty": "30", "unit_price": "80"},
                {"product_id": p2, "qty": "10", "unit_price": "40"},
            ],
        },
        status=201,
    )
    sales.post(f"/sales/quotations/{qt['id']}/send")
    sales.post(f"/sales/quotations/{qt['id']}/accept")
    so = sales.post(f"/sales/quotations/{qt['id']}/convert", {"warehouse_id": wh}, status=201)
    assert (so["status"], so["total"]) == ("draft", "2800.00")
    so = sales.post(f"/sales/orders/{so['id']}/confirm")
    assert so["status"] == "confirmed"
    assert customer_due() == "0.00"

    # 6. Sales: reserve -> reserved, not yet out of stock
    reserved = sales.post(f"/sales/orders/{so['id']}/reserve")
    assert all(line["short"] == "0.000" for line in reserved["lines"])
    assert stock(p1) == ("100.000", "30.000", "70.000", "52.4000")
    assert stock(p2) == ("40.000", "10.000", "30.000", "25.0000")

    # 7. Sales: deliver everything with an invoice (COGS at the current average)
    dlv = sales.post(
        f"/sales/orders/{so['id']}/deliver",
        {
            "create_invoice": True,
            "items": [{"so_item_id": i["id"], "qty": i["qty_ordered"]} for i in so["items"]],
        },
        status=201,
    )
    assert {i["product_id"]: i["unit_cost_cogs"] for i in dlv["items"]} == {
        p1: "52.4000",
        p2: "25.0000",
    }
    assert stock(p1) == ("70.000", "0.000", "70.000", "52.4000")
    assert stock(p2) == ("30.000", "0.000", "30.000", "25.0000")
    invoice = sales.get(f"/sales/invoices/{dlv['invoice_id']}")
    # COGS 30 x 52.40 + 10 x 25 = 1,822
    assert (invoice["total"], invoice["cogs_total"], invoice["status"]) == (
        "2800.00",
        "1822.00",
        "unpaid",
    )
    assert sales.get(f"/sales/orders/{so['id']}")["status"] == "delivered"
    assert customer_due() == "2800.00"

    # 8. Sales: collect 1,000 in cash against the invoice
    sales.post(
        "/money/collections",
        {
            "customer_id": customer["id"],
            "account_id": cash,
            "amount": "1000",
            "invoice_id": invoice["id"],
        },
        status=201,
    )
    invoice = sales.get(f"/sales/invoices/{invoice['id']}")
    assert (invoice["paid_amount"], invoice["outstanding"], invoice["status"]) == (
        "1000.00",
        "1800.00",
        "partial",
    )
    assert customer_due() == "1800.00"
    assert balances() == ("7000.00", "0.00")

    # 9. Accounts: collect the remaining 1,800 by bank
    accounts.post(
        "/money/collections",
        {
            "customer_id": customer["id"],
            "account_id": bank,
            "amount": "1800",
            "invoice_id": invoice["id"],
        },
        status=201,
    )
    invoice = owner.get(f"/sales/invoices/{invoice['id']}")
    assert (invoice["outstanding"], invoice["status"]) == ("0.00", "paid")
    assert customer_due() == "0.00"
    assert balances() == ("7000.00", "1800.00")

    # 10. Accounts: rent expense 500 from cash
    accounts.post(
        "/money/expenses",
        {"expense_category_id": rent, "account_id": cash, "amount": "500"},
        status=201,
    )
    assert balances() == ("6500.00", "1800.00")

    # 11. Owner: dashboard
    d = owner.get("/dashboard/summary")
    assert d["today_sales"] == "2800.00"
    assert d["today_collection"] == "2800.00"
    assert d["today_expenses"] == "500.00"
    assert d["today_purchase"] == "6140.00"  # 3,933.33 + 2,206.67
    assert (d["cash_balance"], d["bank_balance"], d["mfs_balance"]) == (
        "6500.00",
        "1800.00",
        "0.00",
    )
    assert (d["customer_due"], d["supplier_due"]) == ("0.00", "2140.00")
    assert d["inventory_value"] == "4418.00"  # 70 x 52.40 + 30 x 25
    assert (d["pending_orders_count"], d["pending_orders_value"]) == (0, "0.00")
    # 2,800 sales - 1,822 COGS + 10,000 other income - 500 expenses
    assert d["estimated_profit_mtd"] == "10478.00"
    assert d["sales_vs_collection"][-1]["sales"] == "2800.00"
    assert d["sales_vs_collection"][-1]["collection"] == "2800.00"
