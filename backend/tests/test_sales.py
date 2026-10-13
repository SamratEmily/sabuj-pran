"""Sales: quotations, orders, reservation, delivery + invoice, collections against invoices,
sales returns with refunds, cancel rules and atomicity."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.dates import today
from app.core.errors import AppError
from app.modules.auth.models import AuditLog, User
from app.modules.inventory import service as inventory
from app.modules.inventory.models import PURCHASE_IN, SALE_RETURN_IN, StockTransaction
from app.modules.master.models import Product, Warehouse
from app.modules.money import service as money
from app.modules.money.models import MoneyAccount
from app.modules.parties import service as parties
from app.modules.parties.models import CUSTOMER, PartyLedger
from app.modules.parties.schemas import PartyIn
from app.modules.sales import service as sales
from app.modules.sales.models import Delivery, Invoice, SalesOrder, SalesReturn
from app.modules.sales.schemas import DeliverIn
from tests.conftest import MakeUser, auth_headers

API = "/api/v1/sales"
D = Decimal


@pytest.fixture
def env(db: Session, admin: User) -> dict[str, int]:
    products = dict(db.execute(select(Product.code, Product.id)).all())
    wh = db.scalar(select(Warehouse.id).where(Warehouse.code == "MAIN"))
    accounts = dict(db.execute(select(MoneyAccount.name, MoneyAccount.id)).all())
    cust = parties.create_party(db, admin, parties.CUSTOMERS, PartyIn(name="Rahim Traders"))
    other = parties.create_party(db, admin, parties.CUSTOMERS, PartyIn(name="Karim Store"))
    assert wh is not None
    return {
        "p1": products["P-0001"],
        "p2": products["P-0002"],
        "wh": wh,
        "cust": cust.id,
        "other": other.id,
        "cash": accounts["Cash in Hand"],
    }


def add_stock(db: Session, admin: User, env: dict[str, int], key: str, qty: str, cost: str) -> None:
    inventory.stock_in(
        db, env[key], env["wh"], D(qty), D(cost), PURCHASE_IN, "TEST", None, today(), admin
    )
    db.commit()


def so_body(
    env: dict[str, int], discount: str = "0", customer: str = "cust", **lines: tuple[str, str]
) -> dict:
    lines = lines or {"p1": ("10", "100"), "p2": ("5", "40")}
    return {
        "customer_id": env[customer],
        "warehouse_id": env["wh"],
        "discount": discount,
        "items": [{"product_id": env[k], "qty": q, "unit_price": p} for k, (q, p) in lines.items()],
    }


def confirmed_order(client: TestClient, h: dict, env: dict[str, int], **kw: object) -> dict:
    so = client.post(f"{API}/orders", headers=h, json=so_body(env, **kw))  # type: ignore[arg-type]
    assert so.status_code == 201, so.text
    res = client.post(f"{API}/orders/{so.json()['id']}/confirm", headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "confirmed"
    return res.json()


def line_id(so: dict, env: dict[str, int], key: str) -> int:
    return next(i["id"] for i in so["items"] if i["product_id"] == env[key])


def deliver(
    client: TestClient, h: dict, so: dict, items: list[tuple[int, str]], invoice: bool = True
):  # noqa: ANN201
    return client.post(
        f"{API}/orders/{so['id']}/deliver",
        headers=h,
        json={
            "create_invoice": invoice,
            "items": [{"so_item_id": i, "qty": q} for i, q in items],
        },
    )


def stock(db: Session, env: dict[str, int], key: str) -> tuple[Decimal, Decimal, Decimal]:
    db.expire_all()
    b = inventory.get_balance(db, env[key], env["wh"])
    return (b.qty_on_hand, b.qty_reserved, b.avg_cost) if b else (D("0"), D("0"), D("0"))


def due(db: Session, env: dict[str, int], key: str = "cust") -> Decimal:
    return parties.get_balance(db, CUSTOMER, env[key])


def counts(db: Session) -> tuple[int, ...]:
    db.expire_all()
    return tuple(
        db.scalar(select(func.count()).select_from(m)) or 0
        for m in (Delivery, Invoice, SalesReturn, StockTransaction, PartyLedger)
    )


# --- quotations ------------------------------------------------------------------------


def test_quotation_converts_to_draft_sales_order(
    client: TestClient, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    body = so_body(env, discount="50")
    body.pop("warehouse_id")
    qt = client.post(f"{API}/quotations", headers=h, json=body)
    assert qt.status_code == 201, qt.text
    qt = qt.json()
    assert (qt["qt_number"], qt["status"], qt["total"]) == ("QT-000001", "draft", "1150.00")

    assert client.post(f"{API}/quotations/{qt['id']}/accept", headers=h).status_code == 400
    sent = client.post(f"{API}/quotations/{qt['id']}/send", headers=h).json()
    assert sent["status"] == "sent"
    assert client.post(f"{API}/quotations/{qt['id']}/accept", headers=h).json()["status"] == (
        "accepted"
    )

    res = client.post(f"{API}/quotations/{qt['id']}/convert", headers=h, json={})
    assert res.status_code == 201, res.text
    so = res.json()
    assert (so["so_number"], so["status"], so["quotation_number"]) == (
        "SO-000001",
        "draft",
        "QT-000001",
    )
    assert (so["subtotal"], so["discount"], so["total"]) == ("1200.00", "50.00", "1150.00")
    assert [(i["product_id"], i["qty_ordered"], i["unit_price"]) for i in so["items"]] == [
        (i["product_id"], i["qty"], i["unit_price"]) for i in qt["items"]
    ]
    assert so["warehouse_id"] == env["wh"]  # default warehouse

    after = client.get(f"{API}/quotations/{qt['id']}", headers=h).json()
    assert (after["status"], after["converted_order_number"]) == ("converted", "SO-000001")
    # converted quotations can't be edited or converted again
    assert client.put(f"{API}/quotations/{qt['id']}", headers=h, json=body).status_code == 400
    again = client.post(f"{API}/quotations/{qt['id']}/convert", headers=h, json={})
    assert again.json()["code"] == "INVALID_STATUS"


# --- reservation -----------------------------------------------------------------------


def test_reserve_partial_when_stock_is_short(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    add_stock(db, admin, env, "p1", "6", "50")
    add_stock(db, admin, env, "p2", "8", "20")
    so = confirmed_order(client, h, env)

    res = client.post(f"{API}/orders/{so['id']}/reserve", headers=h, json={})
    assert res.status_code == 200, res.text
    lines = {r["so_item_id"]: r for r in res.json()["lines"]}
    p1, p2 = lines[line_id(so, env, "p1")], lines[line_id(so, env, "p2")]
    assert (p1["wanted"], p1["reserved_now"], p1["short"]) == ("10.000", "6.000", "4.000")
    assert (p2["wanted"], p2["reserved_now"], p2["short"]) == ("5.000", "5.000", "0.000")
    assert stock(db, env, "p1")[:2] == (D("6"), D("6"))
    assert stock(db, env, "p2")[:2] == (D("8"), D("5"))
    detail = res.json()["order"]
    row = next(i for i in detail["items"] if i["product_id"] == env["p1"])
    assert (row["qty_reserved"], row["qty_available"], row["qty_remaining"]) == (
        "6.000",
        "0.000",
        "10.000",
    )

    # reserving again doesn't double-reserve; new stock tops it up
    again = client.post(f"{API}/orders/{so['id']}/reserve", headers=h, json={}).json()
    assert all(r["reserved_now"] == "0.000" for r in again["lines"])
    add_stock(db, admin, env, "p1", "10", "50")
    topped = client.post(f"{API}/orders/{so['id']}/reserve", headers=h, json={}).json()
    p1 = next(r for r in topped["lines"] if r["so_item_id"] == line_id(so, env, "p1"))
    assert (p1["reserved_now"], p1["reserved_total"]) == ("4.000", "10.000")
    assert stock(db, env, "p1")[:2] == (D("16"), D("10"))

    # release gives it all back
    released = client.post(f"{API}/orders/{so['id']}/release", headers=h).json()
    assert all(i["qty_reserved"] == "0.000" for i in released["items"])
    assert stock(db, env, "p1")[1] == D("0") and stock(db, env, "p2")[1] == D("0")


def test_reserve_requires_confirmed_order_and_locks_warehouse(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    add_stock(db, admin, env, "p1", "10", "50")
    draft = client.post(f"{API}/orders", headers=h, json=so_body(env)).json()
    res = client.post(f"{API}/orders/{draft['id']}/reserve", headers=h, json={})
    assert res.json()["code"] == "INVALID_STATUS"

    so = confirmed_order(client, h, env)
    client.post(f"{API}/orders/{so['id']}/reserve", headers=h, json={})
    other_wh = Warehouse(name="Branch", code="BR1", address="")
    db.add(other_wh)
    db.commit()
    res = client.post(
        f"{API}/orders/{so['id']}/reserve", headers=h, json={"warehouse_id": other_wh.id}
    )
    assert res.json()["code"] == "WAREHOUSE_LOCKED"


# --- delivery --------------------------------------------------------------------------


def test_delivery_consumes_reservation_first(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    add_stock(db, admin, env, "p1", "10", "50")
    so_a = confirmed_order(client, h, env, p1=("10", "100"))
    client.post(f"{API}/orders/{so_a['id']}/reserve", headers=h, json={})
    assert stock(db, env, "p1")[:2] == (D("10"), D("10"))

    # another order can't take reserved stock
    so_b = confirmed_order(client, h, env, customer="other", p1=("2", "100"))
    res = deliver(client, h, so_b, [(line_id(so_b, env, "p1"), "2")])
    assert res.json()["code"] == "INSUFFICIENT_STOCK"

    res = deliver(client, h, so_a, [(line_id(so_a, env, "p1"), "4")])
    assert res.status_code == 201, res.text
    assert stock(db, env, "p1")[:2] == (D("6"), D("6"))  # 4 came out of the reservation
    detail = client.get(f"{API}/orders/{so_a['id']}", headers=h).json()
    line = detail["items"][0]
    assert (line["qty_delivered"], line["qty_reserved"], line["qty_remaining"]) == (
        "4.000",
        "6.000",
        "6.000",
    )
    assert detail["status"] == "partially_delivered"


def test_deliver_beyond_remaining_or_stock_is_rejected(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    add_stock(db, admin, env, "p1", "20", "50")
    so = confirmed_order(client, h, env, p1=("10", "100"))
    pid = line_id(so, env, "p1")
    assert deliver(client, h, so, [(pid, "11")]).json()["code"] == "OVER_DELIVERY"
    assert deliver(client, h, so, [(pid, "8")]).status_code == 201
    assert deliver(client, h, so, [(pid, "3")]).json()["code"] == "OVER_DELIVERY"

    so2 = confirmed_order(client, h, env, customer="other", p1=("15", "100"))
    res = deliver(client, h, so2, [(line_id(so2, env, "p1"), "13")])  # only 12 on hand
    assert res.status_code == 400
    assert res.json()["code"] == "INSUFFICIENT_STOCK"
    assert stock(db, env, "p1")[0] == D("12")

    draft = client.post(f"{API}/orders", headers=h, json=so_body(env)).json()
    res = deliver(client, h, draft, [(line_id(draft, env, "p1"), "1")])
    assert res.json()["code"] == "INVALID_STATUS"


def test_partial_deliveries_statuses_and_discount_shares(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    add_stock(db, admin, env, "p1", "10", "50")
    add_stock(db, admin, env, "p2", "5", "20")
    so = confirmed_order(client, h, env, discount="100.01")
    p1, p2 = line_id(so, env, "p1"), line_id(so, env, "p2")

    first = deliver(client, h, so, [(p1, "3")])
    assert first.status_code == 201, first.text
    assert client.get(f"{API}/orders/{so['id']}", headers=h).json()["status"] == (
        "partially_delivered"
    )
    deliver(client, h, so, [(p1, "7"), (p2, "2")])
    last = deliver(client, h, so, [(p2, "3")])
    assert last.status_code == 201

    detail = client.get(f"{API}/orders/{so['id']}", headers=h).json()
    assert detail["status"] == "delivered"
    assert [d["dlv_number"] for d in detail["deliveries"]] == [
        "DLV-000001",
        "DLV-000002",
        "DLV-000003",
    ]
    invoices = detail["invoices"]
    assert [i["inv_number"] for i in invoices] == ["INV-000001", "INV-000002", "INV-000003"]
    assert [i["subtotal"] for i in invoices] == ["300.00", "780.00", "120.00"]
    assert [i["discount"] for i in invoices] == ["25.00", "65.01", "10.00"]
    assert sum(D(i["discount"]) for i in invoices) == D("100.01")
    assert sum(D(i["total"]) for i in invoices) == D(so["total"]) == D("1099.99")
    assert due(db, env) == D("1099.99")

    # a delivered order accepts nothing more
    assert deliver(client, h, so, [(p1, "1")]).json()["code"] == "INVALID_STATUS"


def test_cogs_equals_average_cost_at_delivery_time(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    add_stock(db, admin, env, "p1", "10", "100")
    add_stock(db, admin, env, "p1", "10", "130")  # avg 115
    so = confirmed_order(client, h, env, p1=("8", "200"))
    pid = line_id(so, env, "p1")

    dlv = deliver(client, h, so, [(pid, "5")]).json()
    assert dlv["items"][0]["unit_cost_cogs"] == "115.0000"
    inv = client.get(f"{API}/invoices/{dlv['invoice_id']}", headers=h).json()
    assert (inv["cogs_total"], inv["total"]) == ("575.00", "1000.00")

    add_stock(db, admin, env, "p1", "5", "175")  # avg (15*115 + 875) / 20 = 130
    assert stock(db, env, "p1")[2] == D("130.0000")
    dlv2 = deliver(client, h, so, [(pid, "3")]).json()
    assert dlv2["items"][0]["unit_cost_cogs"] == "130.0000"


# --- invoices & collections ------------------------------------------------------------


def test_invoice_posts_due_and_collections_drive_its_status(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    add_stock(db, admin, env, "p1", "10", "50")
    add_stock(db, admin, env, "p2", "5", "20")
    so = confirmed_order(client, h, env, discount="120")
    dlv = deliver(client, h, so, [(i["id"], i["qty_ordered"]) for i in so["items"]]).json()
    inv_id = dlv["invoice_id"]
    inv = client.get(f"{API}/invoices/{inv_id}", headers=h).json()
    assert (inv["total"], inv["status"], inv["outstanding"]) == ("1080.00", "unpaid", "1080.00")
    assert due(db, env) == D("1080.00")
    debit = db.scalar(select(PartyLedger).where(PartyLedger.ref_type == "INVOICE"))
    assert debit is not None and (debit.debit, debit.ref_id) == (D("1080.00"), inv_id)

    def collect(amount: str, customer: str = "cust"):  # noqa: ANN202
        return client.post(
            "/api/v1/money/collections",
            headers=h,
            json={
                "customer_id": env[customer],
                "account_id": env["cash"],
                "amount": amount,
                "invoice_id": inv_id,
            },
        )

    first = collect("500")
    assert first.status_code == 201, first.text
    assert first.json()["invoice_number"] == "INV-000001"
    inv = client.get(f"{API}/invoices/{inv_id}", headers=h).json()
    assert (inv["paid_amount"], inv["status"], inv["outstanding"]) == (
        "500.00",
        "partial",
        "580.00",
    )
    assert collect("600").json()["code"] == "OVERPAYMENT"
    assert collect("10", customer="other").json()["code"] == "INVALID_INVOICE"
    second = collect("580").json()
    inv = client.get(f"{API}/invoices/{inv_id}", headers=h).json()
    assert (inv["status"], inv["outstanding"], len(inv["collections"])) == ("paid", "0.00", 2)
    assert due(db, env) == D("0.00")

    # reversing a collection restores paid_amount and status
    rev = client.post(f"/api/v1/money/collections/{second['id']}/reverse", headers=h, json={})
    assert rev.status_code == 200, rev.text
    inv = client.get(f"{API}/invoices/{inv_id}", headers=h).json()
    assert (inv["paid_amount"], inv["status"]) == ("500.00", "partial")
    assert due(db, env) == D("580.00")

    listed = client.get(f"{API}/invoices", headers=h, params={"status": "partial"}).json()
    assert [i["inv_number"] for i in listed["items"]] == ["INV-000001"]


def test_delivery_without_invoice_can_be_invoiced_later(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    add_stock(db, admin, env, "p1", "10", "50")
    so = confirmed_order(client, h, env, p1=("4", "100"))
    dlv = deliver(client, h, so, [(line_id(so, env, "p1"), "4")], invoice=False).json()
    assert dlv["invoice_id"] is None
    assert due(db, env) == D("0")

    res = client.post(f"{API}/deliveries/{dlv['id']}/invoice", headers=h)
    assert res.status_code == 201, res.text
    assert (res.json()["total"], res.json()["dlv_number"]) == ("400.00", dlv["dlv_number"])
    assert due(db, env) == D("400.00")
    again = client.post(f"{API}/deliveries/{dlv['id']}/invoice", headers=h)
    assert again.json()["code"] == "ALREADY_INVOICED"


# --- sales returns ---------------------------------------------------------------------


def _invoiced(client: TestClient, db: Session, admin: User, env: dict[str, int]) -> dict:
    """10 x P1 @ 100 (cost 115 avg) + 5 x P2 @ 40, discount 120, fully delivered."""
    h = auth_headers(admin)
    add_stock(db, admin, env, "p1", "10", "100")
    add_stock(db, admin, env, "p1", "10", "130")
    add_stock(db, admin, env, "p2", "5", "20")
    so = confirmed_order(client, h, env, discount="120")
    dlv = deliver(client, h, so, [(i["id"], i["qty_ordered"]) for i in so["items"]]).json()
    return client.get(f"{API}/invoices/{dlv['invoice_id']}", headers=h).json()


def test_sales_return_restores_stock_at_original_cogs_and_reduces_due(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    inv = _invoiced(client, db, admin, env)
    assert due(db, env) == D("1080.00")
    add_stock(db, admin, env, "p1", "10", "200")  # avg now (10*115 + 2000) / 20 = 157.5
    assert stock(db, env, "p1")[::2] == (D("20"), D("157.5000"))
    p1 = next(i for i in inv["items"] if i["product_id"] == env["p1"])

    res = client.post(
        f"{API}/invoices/{inv['id']}/return",
        headers=h,
        json={"items": [{"invoice_item_id": p1["id"], "qty": "2"}]},
    )
    assert res.status_code == 201, res.text
    ret = res.json()
    # 200 gross, discount share 120 * 200 / 1200 = 20
    assert (ret["srn_number"], ret["subtotal"], ret["discount"], ret["total"]) == (
        "SRN-000001",
        "200.00",
        "20.00",
        "180.00",
    )
    row = db.scalar(select(StockTransaction).where(StockTransaction.txn_type == SALE_RETURN_IN))
    assert row is not None and (row.qty_in, row.unit_cost) == (D("2"), D("115.0000"))
    # (20 * 157.5 + 2 * 115) / 22 = 153.6364
    assert stock(db, env, "p1")[::2] == (D("22"), D("153.6364"))
    assert due(db, env) == D("900.00")

    inv = client.get(f"{API}/invoices/{inv['id']}", headers=h).json()
    p1 = next(i for i in inv["items"] if i["product_id"] == env["p1"])
    assert (p1["qty_returned"], p1["qty_returnable"]) == ("2.000", "8.000")
    assert (inv["returned_amount"], inv["outstanding"], inv["status"]) == (
        "180.00",
        "900.00",
        "unpaid",
    )
    over = client.post(
        f"{API}/invoices/{inv['id']}/return",
        headers=h,
        json={"items": [{"invoice_item_id": p1["id"], "qty": "9"}]},
    )
    assert over.json()["code"] == "OVER_RETURN"


def test_refund_moves_money_and_debits_customer(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    inv = _invoiced(client, db, admin, env)
    paid = client.post(
        "/api/v1/money/collections",
        headers=h,
        json={
            "customer_id": env["cust"],
            "account_id": env["cash"],
            "amount": "1080",
            "invoice_id": inv["id"],
        },
    )
    assert paid.status_code == 201, paid.text
    assert due(db, env) == D("0.00")
    p2 = next(i for i in inv["items"] if i["product_id"] == env["p2"])

    body = {
        "refund_amount": "72",
        "refund_account_id": env["cash"],
        "items": [{"invoice_item_id": p2["id"], "qty": "2"}],
    }
    too_much = client.post(
        f"{API}/invoices/{inv['id']}/return", headers=h, json=body | {"refund_amount": "73"}
    )
    assert too_much.json()["code"] == "INVALID_REFUND"
    no_account = client.post(
        f"{API}/invoices/{inv['id']}/return", headers=h, json=body | {"refund_account_id": None}
    )
    assert no_account.json()["code"] == "ACCOUNT_REQUIRED"

    res = client.post(f"{API}/invoices/{inv['id']}/return", headers=h, json=body)
    assert res.status_code == 201, res.text
    ret = res.json()
    assert (ret["total"], ret["refund_amount"], ret["refund_account_name"]) == (
        "72.00",
        "72.00",
        "Cash in Hand",
    )
    db.expire_all()
    assert db.get(MoneyAccount, env["cash"]).balance == D("1008.00")  # type: ignore[union-attr]
    assert money.ledger_balance(db, env["cash"]) == D("1008.00")
    assert due(db, env) == D("0.00")  # credit 72 for the goods, debit 72 for the cash
    inv = client.get(f"{API}/invoices/{inv['id']}", headers=h).json()
    assert (inv["refunded_amount"], inv["status"], inv["outstanding"]) == ("72.00", "paid", "0.00")
    assert [r["srn_number"] for r in inv["returns"]] == ["SRN-000001"]


def test_refund_without_funds_rolls_back_the_whole_return(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    inv = _invoiced(client, db, admin, env)
    before = counts(db), stock(db, env, "p2")
    p2 = next(i for i in inv["items"] if i["product_id"] == env["p2"])
    res = client.post(
        f"{API}/invoices/{inv['id']}/return",
        headers=h,
        json={
            "refund_amount": "10",
            "refund_account_id": env["cash"],  # empty
            "items": [{"invoice_item_id": p2["id"], "qty": "1"}],
        },
    )
    assert res.json()["code"] == "INSUFFICIENT_FUNDS"
    assert (counts(db), stock(db, env, "p2")) == before
    inv = client.get(f"{API}/invoices/{inv['id']}", headers=h).json()
    assert inv["returned_amount"] == "0.00"
    assert all(i["qty_returned"] == "0.000" for i in inv["items"])
    assert due(db, env) == D("1080.00")


# --- edit / cancel rules ---------------------------------------------------------------


def test_cancel_releases_reservation_and_rules(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    add_stock(db, admin, env, "p1", "20", "50")
    so = confirmed_order(client, h, env, p1=("5", "100"))
    client.post(f"{API}/orders/{so['id']}/reserve", headers=h, json={})
    assert stock(db, env, "p1")[1] == D("5")
    # edit only while draft
    assert client.put(f"{API}/orders/{so['id']}", headers=h, json=so_body(env)).status_code == 400

    res = client.post(f"{API}/orders/{so['id']}/cancel", headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "cancelled"
    assert stock(db, env, "p1")[1] == D("0")
    assert client.post(f"{API}/orders/{so['id']}/confirm", headers=h).status_code == 400

    delivered = confirmed_order(client, h, env, p1=("5", "100"))
    deliver(client, h, delivered, [(line_id(delivered, env, "p1"), "1")])
    res = client.post(f"{API}/orders/{delivered['id']}/cancel", headers=h)
    assert res.json()["code"] == "CANNOT_CANCEL"

    # manual "produced" figure
    pid = line_id(delivered, env, "p1")
    ok = client.put(
        f"{API}/orders/{delivered['id']}/items/{pid}/produced",
        headers=h,
        json={"qty_produced": "3"},
    )
    assert ok.json()["items"][0]["qty_produced"] == "3.000"
    too_many = client.put(
        f"{API}/orders/{delivered['id']}/items/{pid}/produced",
        headers=h,
        json={"qty_produced": "6"},
    )
    assert too_many.json()["code"] == "INVALID_QTY"


# --- atomicity -------------------------------------------------------------------------


@pytest.mark.parametrize("failing", ["stock_out", "post_party_entry"])
def test_delivery_rolls_back_entirely_when_any_step_fails(
    client: TestClient,
    db: Session,
    admin: User,
    env: dict[str, int],
    monkeypatch: pytest.MonkeyPatch,
    failing: str,
) -> None:
    h = auth_headers(admin)
    add_stock(db, admin, env, "p1", "10", "50")
    add_stock(db, admin, env, "p2", "5", "20")
    so = confirmed_order(client, h, env, discount="120")
    client.post(f"{API}/orders/{so['id']}/reserve", headers=h, json={})
    before = counts(db), stock(db, env, "p1"), stock(db, env, "p2")

    if failing == "stock_out":
        real = inventory.stock_out
        calls = {"n": 0}

        def flaky(*args: object, **kwargs: object) -> object:
            calls["n"] += 1
            if calls["n"] == 2:
                raise AppError(500, "BOOM", "simulated stock failure on line 2")
            return real(*args, **kwargs)

        monkeypatch.setattr(inventory, "stock_out", flaky)
    else:

        def boom(*args: object, **kwargs: object) -> None:
            raise AppError(500, "BOOM", "simulated ledger failure")

        monkeypatch.setattr(parties, "post_party_entry", boom)

    with pytest.raises(AppError, match="simulated"):
        sales.deliver(
            db,
            admin,
            so["id"],
            DeliverIn(
                items=[{"so_item_id": i["id"], "qty": i["qty_ordered"]} for i in so["items"]]
            ),
        )

    assert (counts(db), stock(db, env, "p1"), stock(db, env, "p2")) == before
    order = db.get(SalesOrder, so["id"])
    assert order is not None and order.status == "confirmed"
    assert all(i.qty_delivered == 0 and i.qty_reserved == i.qty_ordered for i in order.items)
    assert due(db, env) == D("0")
    monkeypatch.undo()
    # the rolled-back delivery did not consume numbers
    ok = deliver(client, h, so, [(i["id"], i["qty_ordered"]) for i in so["items"]])
    assert ok.status_code == 201, ok.text
    assert (ok.json()["dlv_number"], ok.json()["inv_number"]) == ("DLV-000001", "INV-000001")


# --- permissions & audit ---------------------------------------------------------------


def test_permissions_and_audit(
    client: TestClient, db: Session, admin: User, env: dict[str, int], make_user: MakeUser
) -> None:
    store = db.scalar(select(User).where(User.username == "store"))
    assert store is not None
    assert client.get(f"{API}/orders", headers=auth_headers(store)).status_code == 403
    assert (
        client.post(f"{API}/orders", headers=auth_headers(store), json=so_body(env)).status_code
        == 403
    )

    add_stock(db, admin, env, "p1", "10", "50")
    so = confirmed_order(client, auth_headers(admin), env, p1=("4", "100"))
    picker = make_user(permissions=["delivery.create", "sales_order.view"])
    hp = auth_headers(picker)
    pid = line_id(so, env, "p1")
    assert deliver(client, hp, so, [(pid, "1")]).status_code == 403  # invoice.create missing
    assert deliver(client, hp, so, [(pid, "1")], invoice=False).status_code == 201
    assert client.post(f"{API}/orders/{so['id']}/reserve", headers=hp, json={}).status_code == 403

    actions = set(
        db.execute(
            select(AuditLog.entity_type, AuditLog.action).where(
                AuditLog.entity_type.in_(("sales_order", "delivery"))
            )
        ).all()
    )
    assert {("sales_order", "create"), ("sales_order", "approve"), ("delivery", "post")} <= actions
