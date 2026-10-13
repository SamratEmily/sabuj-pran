"""Dashboard: every metric from a small known data set (hand-calculated, including returns,
discounts, reversals, payroll and the profit formula), plus role-aware sections.

"Today" is pinned to 2025-06-15 (Asia/Dhaka business date); documents are dated around it.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import User
from app.modules.dashboard import service as dashboard
from app.modules.master.models import ExpenseCategory, IncomeCategory, Product, Warehouse
from app.modules.money.models import MoneyAccount
from tests.conftest import auth_headers

TODAY = "2025-06-15"
YESTERDAY = "2025-06-14"
LAST_MONTH = "2025-05-20"


@pytest.fixture
def data(
    client: TestClient, db: Session, admin: User, monkeypatch: pytest.MonkeyPatch
) -> dict[str, int]:
    monkeypatch.setattr(dashboard, "today", lambda: date(2025, 6, 15))
    h = auth_headers(admin)

    def post(path: str, body: dict | None = None) -> dict:
        res = client.post(f"/api/v1{path}", headers=h, json=body if body is not None else {})
        assert res.status_code in (200, 201), f"{path}: {res.text}"
        return res.json()

    accounts = dict(db.execute(select(MoneyAccount.name, MoneyAccount.id)).all())
    cash, bank = accounts["Cash in Hand"], accounts["City Bank"]
    products = dict(db.execute(select(Product.code, Product.id)).all())
    p1, p2 = products["P-0001"], products["P-0002"]
    wh = db.scalar(select(Warehouse.id).where(Warehouse.code == "MAIN"))
    rent = db.scalar(select(ExpenseCategory.id).where(ExpenseCategory.name == "Rent"))
    other = db.scalar(select(IncomeCategory.id))
    product = db.get(Product, p1)
    assert product is not None
    product.reorder_level = Decimal("5")  # P1 ends at 4 -> low stock
    db.commit()

    sup = post("/suppliers", {"name": "Plastic Mills"})
    c1 = post("/customers", {"name": "Rahim Traders"})
    c2 = post("/customers", {"name": "Karim Store"})
    c3 = post("/customers", {"name": "Advance Ltd"})

    def money(kind: str, body: dict) -> dict:
        return post(f"/money/{kind}", body)

    # funding last month (outside month-to-date)
    money("incomes", {"income_category_id": other, "account_id": cash, "amount": "10000",
                      "income_date": "2025-05-01"})  # fmt: skip

    # --- purchase today: direct 10 x P1 @100 + 20 x P2 @50, discount 100 -> 1,900
    po = post(
        "/purchase/direct",
        {
            "supplier_id": sup["id"],
            "warehouse_id": wh,
            "order_date": TODAY,
            "discount": "100",
            "items": [
                {"product_id": p1, "qty": "10", "unit_cost": "100"},
                {"product_id": p2, "qty": "20", "unit_cost": "50"},
            ],
        },
    )
    grn = po["receipts"][0]
    p2_line = next(i for i in grn["items"] if i["product_id"] == p2)
    # return 2 x P2: 100 gross - 5 discount share = 95
    post(
        f"/purchase/receipts/{grn['id']}/return",
        {"return_date": TODAY, "items": [{"grn_item_id": p2_line["id"], "qty": "2"}]},
    )

    # --- sales
    def order(customer: int, lines: list[tuple[int, str, str]], discount: str = "0") -> dict:
        so = post(
            "/sales/orders",
            {
                "customer_id": customer,
                "warehouse_id": wh,
                "discount": discount,
                "items": [{"product_id": p, "qty": q, "unit_price": pr} for p, q, pr in lines],
            },
        )
        return post(f"/sales/orders/{so['id']}/confirm")

    def deliver(so: dict, qty: dict[int, str], day: str) -> dict:
        return post(
            f"/sales/orders/{so['id']}/deliver",
            {
                "delivery_date": day,
                "items": [
                    {"so_item_id": i["id"], "qty": qty[i["product_id"]]}
                    for i in so["items"]
                    if i["product_id"] in qty
                ],
            },
        )

    # SO1 (C1): 4 x P1 @200 + 10 x P2 @80, discount 60 -> 1,540; COGS 400 + 500
    so1 = order(c1["id"], [(p1, "4", "200"), (p2, "10", "80")], discount="60")
    dlv1 = deliver(so1, {p1: "4", p2: "10"}, TODAY)
    # SO2 (C2): 5 x P1 @200, 2 delivered yesterday -> invoice 400 (COGS 200), 3 pending
    so2 = order(c2["id"], [(p1, "5", "200")])
    deliver(so2, {p1: "2"}, YESTERDAY)
    # SO3 (C2): 1 x P2 @80, discount 10 -> 70 pending; a draft order doesn't count
    order(c2["id"], [(p2, "1", "80")], discount="10")
    post(
        "/sales/orders",
        {"customer_id": c1["id"], "warehouse_id": wh, "items": [
            {"product_id": p1, "qty": "1", "unit_price": "1"}]},
    )  # fmt: skip

    # --- money today / yesterday
    money("collections", {"customer_id": c1["id"], "account_id": cash, "amount": "1000",
                          "collection_date": TODAY, "invoice_id": dlv1["invoice_id"]})  # fmt: skip
    money("collections", {"customer_id": c2["id"], "account_id": bank, "amount": "100",
                          "collection_date": YESTERDAY})  # fmt: skip
    money(
        "collections",
        {"customer_id": c3["id"], "account_id": cash, "amount": "200", "collection_date": TODAY},
    )  # fmt: skip  (advance: due -200)
    reversed_col = money("collections", {"customer_id": c1["id"], "account_id": cash,
                                         "amount": "50", "collection_date": TODAY})  # fmt: skip
    post(f"/money/collections/{reversed_col['id']}/reverse")
    # sales return today: 2 x P2 @80 = 160 - 6 discount share = 154; refund 54 from cash
    invoice = client.get(f"/api/v1/sales/invoices/{dlv1['invoice_id']}", headers=h).json()
    p2_inv = next(i for i in invoice["items"] if i["product_id"] == p2)
    post(
        f"/sales/invoices/{invoice['id']}/return",
        {
            "return_date": TODAY,
            "refund_amount": "54",
            "refund_account_id": cash,
            "items": [{"invoice_item_id": p2_inv["id"], "qty": "2"}],
        },
    )
    money("supplier-payments", {"supplier_id": sup["id"], "account_id": bank, "amount": "80",
                                "payment_date": TODAY})  # fmt: skip
    money("expenses", {"expense_category_id": rent, "account_id": cash, "amount": "300",
                       "expense_date": TODAY})  # fmt: skip
    reversed_exp = money("expenses", {"expense_category_id": rent, "account_id": cash,
                                      "amount": "40", "expense_date": TODAY})  # fmt: skip
    post(f"/money/expenses/{reversed_exp['id']}/reverse")
    money("expenses", {"expense_category_id": rent, "account_id": cash, "amount": "200",
                       "expense_date": YESTERDAY})  # fmt: skip
    money("expenses", {"expense_category_id": rent, "account_id": cash, "amount": "500",
                       "expense_date": LAST_MONTH})  # fmt: skip
    money("incomes", {"income_category_id": other, "account_id": cash, "amount": "250",
                      "income_date": "2025-06-10"})  # fmt: skip

    # payroll for May paid today: one employee, 3,000
    post("/employees", {"full_name": "Salma Begum", "base_salary": "3000"})
    run = post("/employees/payroll", {"month": "2025-05"})
    post(f"/employees/payroll/{run['id']}/pay", {"account_id": cash, "payment_date": TODAY})
    return {"c1": c1["id"], "c2": c2["id"], "sup": sup["id"], "p1": p1}


def test_every_metric_matches_the_hand_calculation(
    client: TestClient, admin: User, data: dict[str, int]
) -> None:
    res = client.get("/api/v1/dashboard/summary", headers=auth_headers(admin))
    assert res.status_code == 200, res.text
    d = res.json()
    assert (d["as_of"], d["month_start"]) == (TODAY, "2025-06-01")

    # today: sales 1,540 - 154 return; collections 1,000 + 200 (reversed 50 ignored);
    # expenses 300 + payroll 3,000 (reversed 40 ignored); purchase 1,900 - 95 return
    assert d["today_sales"] == "1386.00"
    assert d["today_collection"] == "1200.00"
    assert d["today_expenses"] == "3300.00"
    assert d["today_purchase"] == "1805.00"

    # cash: 10,000 + 1,000 + 200 + 250 - 54 refund - 300 - 200 - 500 - 3,000 = 7,396
    # (reversed collection / expense net to zero); bank: 100 - 80 = 20
    assert (d["cash_balance"], d["bank_balance"], d["mfs_balance"]) == (
        "7396.00",
        "20.00",
        "0.00",
    )

    # dues: C1 1,540 - 154 + 54 - 1,000 = 440; C2 400 - 100 = 300; C3 -200 (advance, not
    # counted); supplier 1,900 - 95 - 80 = 1,725
    assert d["customer_due"] == "740.00"
    assert [(c["name"], c["due"]) for c in d["top_customers"]] == [
        ("Rahim Traders", "440.00"),
        ("Karim Store", "300.00"),
    ]
    assert d["supplier_due"] == "1725.00"
    assert [(s["name"], s["due"]) for s in d["top_suppliers"]] == [("Plastic Mills", "1725.00")]

    # stock: P1 10 - 4 - 2 = 4 @100; P2 20 - 2 - 10 + 2 = 10 @50
    assert d["inventory_value"] == "900.00"
    assert [(s["product_code"], s["qty_on_hand"], s["reorder_level"]) for s in d["low_stock"]] == [
        ("P-0001", "4.000", "5.000")
    ]

    # pending: SO2 3 x 200 = 600 and SO3 70 (after its discount); drafts excluded
    assert (d["pending_orders_count"], d["pending_orders_value"]) == (2, "670.00")

    # profit (June 1-15): net sales (1,540 + 400 - 154) - net COGS (900 + 200 - 100)
    # + income 250 - expenses (300 + 200 + 3,000) = 1,786 - 1,000 + 250 - 3,500
    assert d["estimated_profit_mtd"] == "-2464.00"

    series = {p["date"]: (p["sales"], p["collection"]) for p in d["sales_vs_collection"]}
    assert list(series) == [f"2025-06-{day:02d}" for day in range(9, 16)]
    assert series[YESTERDAY] == ("400.00", "100.00")
    assert series[TODAY] == ("1386.00", "1200.00")
    assert series["2025-06-10"] == ("0.00", "0.00")


def test_sections_follow_permissions(client: TestClient, db: Session, data: dict[str, int]) -> None:
    def summary(username: str) -> dict:
        user = db.scalar(select(User).where(User.username == username))
        assert user is not None
        res = client.get("/api/v1/dashboard/summary", headers=auth_headers(user))
        assert res.status_code == 200, res.text
        return res.json()

    sales = summary("sales")
    for hidden in (
        "cash_balance",
        "bank_balance",
        "mfs_balance",
        "today_expenses",
        "today_purchase",
        "supplier_due",
        "top_suppliers",
        "inventory_value",
        "estimated_profit_mtd",
    ):
        assert hidden not in sales, hidden
    assert sales["today_sales"] == "1386.00"
    assert sales["customer_due"] == "740.00"
    assert sales["pending_orders_count"] == 2
    assert "low_stock" in sales

    owner = summary("owner")  # every .view permission: everything
    assert set(owner["sections"]) == set(dashboard.SECTIONS)
    assert owner["cash_balance"] == "7396.00"

    accounts = summary("accounts")
    assert accounts["cash_balance"] == "7396.00"
    # Accounts sees invoices (to collect against them) but not stock or orders
    assert accounts["today_sales"] == "1386.00"
    assert "inventory_value" not in accounts and "pending_orders_count" not in accounts

    store = db.scalar(select(User).where(User.username == "store"))
    assert store is not None
    assert "inventory_value" in summary("store")
