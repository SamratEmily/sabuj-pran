"""Purchase: orders, receipts (partial/full/direct), returns, cancel rules, atomicity."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.dates import today
from app.core.errors import AppError
from app.modules.auth.models import AuditLog, User
from app.modules.inventory import service as inventory
from app.modules.inventory.models import SALE_OUT, StockTransaction
from app.modules.master.models import Product, Warehouse
from app.modules.parties import service as parties
from app.modules.parties.models import SUPPLIER, PartyLedger
from app.modules.parties.schemas import PartyIn
from app.modules.purchase.models import GoodsReceipt, PurchaseOrder, PurchaseReturn
from tests.conftest import auth_headers

API = "/api/v1/purchase"
D = Decimal


@pytest.fixture
def env(db: Session, admin: User) -> dict[str, int]:
    products = dict(db.execute(select(Product.code, Product.id)).all())
    wh = db.scalar(select(Warehouse.id).where(Warehouse.code == "MAIN"))
    supplier = parties.create_party(db, admin, parties.SUPPLIERS, PartyIn(name="Plastic Mills"))
    assert wh is not None
    return {"p1": products["P-0001"], "p2": products["P-0002"], "wh": wh, "sup": supplier.id}


def po_body(env: dict[str, int], discount: str = "0", **lines: tuple[str, str]) -> dict:
    lines = lines or {"p1": ("10", "100"), "p2": ("5", "40")}
    return {
        "supplier_id": env["sup"],
        "warehouse_id": env["wh"],
        "discount": discount,
        "items": [{"product_id": env[k], "qty": q, "unit_cost": c} for k, (q, c) in lines.items()],
    }


def create_approved(client: TestClient, h: dict, env: dict[str, int], discount: str = "0") -> dict:
    po = client.post(f"{API}/orders", headers=h, json=po_body(env, discount))
    assert po.status_code == 201, po.text
    approved = client.post(f"{API}/orders/{po.json()['id']}/approve", headers=h)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    return approved.json()


def line_id(po: dict, env: dict[str, int], key: str) -> int:
    return next(i["id"] for i in po["items"] if i["product_id"] == env[key])


def stock(db: Session, env: dict[str, int], key: str) -> tuple[Decimal, Decimal]:
    b = inventory.get_balance(db, env[key], env["wh"])
    return (b.qty_on_hand, b.avg_cost) if b else (D("0"), D("0"))


def due(db: Session, env: dict[str, int]) -> Decimal:
    return parties.get_balance(db, SUPPLIER, env["sup"])


def counts(db: Session) -> tuple[int, int, int]:
    return (
        db.scalar(select(func.count()).select_from(GoodsReceipt)) or 0,
        db.scalar(select(func.count()).select_from(StockTransaction)) or 0,
        db.scalar(select(func.count()).select_from(PartyLedger)) or 0,
    )


# --- receiving -------------------------------------------------------------------------


def test_full_receipt_posts_stock_cost_and_supplier_credit(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    po = create_approved(client, h, env, discount="120")
    assert (po["po_number"], po["subtotal"], po["total"]) == ("PO-000001", "1200.00", "1080.00")

    res = client.post(
        f"{API}/orders/{po['id']}/receive",
        headers=h,
        json={
            "items": [
                {"po_item_id": line_id(po, env, "p1"), "qty": "10"},
                {"po_item_id": line_id(po, env, "p2"), "qty": "5"},
            ]
        },
    )
    assert res.status_code == 201, res.text
    grn = res.json()
    assert (grn["grn_number"], grn["subtotal"], grn["discount"], grn["total"]) == (
        "GRN-000001",
        "1200.00",
        "120.00",
        "1080.00",
    )

    # stock at gross cost (bill-only discount)
    assert stock(db, env, "p1") == (D("10"), D("100.0000"))
    assert stock(db, env, "p2") == (D("5"), D("40.0000"))
    assert due(db, env) == D("1080.00")
    credit = db.scalar(select(PartyLedger).where(PartyLedger.ref_type == "GOODS_RECEIPT"))
    assert credit is not None and (credit.credit, credit.ref_id) == (D("1080.00"), grn["id"])

    detail = client.get(f"{API}/orders/{po['id']}", headers=h).json()
    assert detail["status"] == "received"
    assert [i["remaining_qty"] for i in detail["items"]] == ["0.000", "0.000"]
    assert detail["supplier_due"] == "1080.00"
    assert len(detail["receipts"]) == 1


def test_partial_receipts_twice_with_changed_cost_and_discount_shares(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    po = create_approved(client, h, env, discount="100")  # subtotal 1200
    p1, p2 = line_id(po, env, "p1"), line_id(po, env, "p2")

    first = client.post(
        f"{API}/orders/{po['id']}/receive",
        headers=h,
        json={"items": [{"po_item_id": p1, "qty": "4"}]},
    ).json()
    # share = 100 * 400 / 1200 = 33.33
    assert (first["subtotal"], first["discount"], first["total"]) == ("400.00", "33.33", "366.67")
    detail = client.get(f"{API}/orders/{po['id']}", headers=h).json()
    assert detail["status"] == "partially_received"
    assert [i["received_qty"] for i in detail["items"]] == ["4.000", "0.000"]

    second = client.post(
        f"{API}/orders/{po['id']}/receive",
        headers=h,
        json={
            "items": [
                {"po_item_id": p1, "qty": "6", "unit_cost": "110"},  # supplier raised the price
                {"po_item_id": p2, "qty": "5"},
            ]
        },
    ).json()
    # completing receipt takes the exact remainder of the discount
    assert (second["subtotal"], second["discount"], second["total"]) == (
        "860.00",
        "66.67",
        "793.33",
    )
    assert D(first["discount"]) + D(second["discount"]) == D("100.00")

    assert stock(db, env, "p1") == (D("10"), D("106.0000"))  # (4*100 + 6*110) / 10
    assert due(db, env) == D("1160.00")
    detail = client.get(f"{API}/orders/{po['id']}", headers=h).json()
    assert detail["status"] == "received"
    assert [r["grn_number"] for r in detail["receipts"]] == ["GRN-000001", "GRN-000002"]


def test_receipt_rejections_change_nothing(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    po = create_approved(client, h, env)
    p1 = line_id(po, env, "p1")
    before = counts(db)

    over = client.post(
        f"{API}/orders/{po['id']}/receive",
        headers=h,
        json={"items": [{"po_item_id": p1, "qty": "10.001"}]},
    )
    assert over.status_code == 400 and over.json()["code"] == "OVER_RECEIPT"

    client.post(
        f"{API}/orders/{po['id']}/receive",
        headers=h,
        json={"items": [{"po_item_id": p1, "qty": "7"}]},
    )
    over2 = client.post(
        f"{API}/orders/{po['id']}/receive",
        headers=h,
        json={"items": [{"po_item_id": p1, "qty": "4"}]},
    )
    assert over2.json()["code"] == "OVER_RECEIPT"  # only 3 remaining

    other = client.post(f"{API}/orders", headers=h, json=po_body(env)).json()  # a draft
    wrong_line = client.post(
        f"{API}/orders/{po['id']}/receive",
        headers=h,
        json={"items": [{"po_item_id": other["items"][0]["id"], "qty": "1"}]},
    )
    assert wrong_line.json()["code"] == "INVALID_LINE"
    draft = client.post(
        f"{API}/orders/{other['id']}/receive",
        headers=h,
        json={"items": [{"po_item_id": other["items"][0]["id"], "qty": "1"}]},
    )
    assert draft.json()["code"] == "INVALID_STATUS"

    # only the single successful 7-unit receipt was posted
    grns, txns, ledger = counts(db)
    assert (grns, txns, ledger) == (before[0] + 1, before[1] + 1, before[2] + 1)
    assert stock(db, env, "p1")[0] == D("7")


def test_receipt_refused_for_a_product_deactivated_after_approval(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    po = create_approved(client, h, env)
    db.get(Product, env["p1"]).is_active = False  # type: ignore[union-attr]
    db.flush()
    before = counts(db)
    res = client.post(
        f"{API}/orders/{po['id']}/receive",
        headers=h,
        json={"items": [{"po_item_id": line_id(po, env, "p1"), "qty": "1"}]},
    )
    assert res.json()["code"] == "INACTIVE_PRODUCT"
    assert counts(db) == before


def test_direct_purchase(client: TestClient, db: Session, admin: User, env: dict[str, int]) -> None:
    h = auth_headers(admin)
    body = po_body(env, "50", p1=("3", "150"))
    res = client.post(f"{API}/direct", headers=h, json=body)
    assert res.status_code == 201, res.text
    po = res.json()
    assert po["status"] == "received" and po["approved_by_name"] == admin.full_name
    grn = po["receipts"][0]
    assert grn["is_direct"] is True
    assert (grn["subtotal"], grn["discount"], grn["total"]) == ("450.00", "50.00", "400.00")
    assert stock(db, env, "p1") == (D("3"), D("150.0000"))
    assert due(db, env) == D("400.00")


# --- returns ---------------------------------------------------------------------------


def _received(client: TestClient, h: dict, env: dict[str, int], discount: str = "120") -> dict:
    po = create_approved(client, h, env, discount=discount)
    grn = client.post(
        f"{API}/orders/{po['id']}/receive",
        headers=h,
        json={"items": [{"po_item_id": i["id"], "qty": i["qty"]} for i in po["items"]]},
    ).json()
    return grn


def test_return_reduces_stock_and_supplier_due(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    grn = _received(client, h, env)  # 1200 gross, 120 discount, 1080 due
    g1 = next(i for i in grn["items"] if i["product_id"] == env["p1"])

    res = client.post(
        f"{API}/receipts/{grn['id']}/return",
        headers=h,
        json={"items": [{"grn_item_id": g1["id"], "qty": "3"}]},
    )
    assert res.status_code == 201, res.text
    ret = res.json()
    # 3 x 100 = 300 gross, 10% receipt discount share -> 270 debited
    assert (ret["prn_number"], ret["subtotal"], ret["discount"], ret["total"]) == (
        "PRN-000001",
        "300.00",
        "30.00",
        "270.00",
    )
    assert stock(db, env, "p1") == (D("7"), D("100.0000"))
    assert due(db, env) == D("810.00")
    debit = db.scalar(select(PartyLedger).where(PartyLedger.ref_type == "PURCHASE_RETURN"))
    assert debit is not None and debit.debit == D("270.00")
    out = db.scalar(
        select(StockTransaction).where(StockTransaction.txn_type == "PURCHASE_RETURN_OUT")
    )
    assert out is not None and out.unit_cost == D("100.0000")

    receipt = client.get(f"{API}/receipts/{grn['id']}", headers=h).json()
    line = next(i for i in receipt["items"] if i["id"] == g1["id"])
    assert (line["returned_qty"], line["returnable_qty"]) == ("3.000", "7.000")
    assert [r["prn_number"] for r in receipt["returns"]] == ["PRN-000001"]


def test_returning_everything_returns_the_whole_discount(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    """Rounded shares (0.08 / 0.25 per unit) would leave 0.01 owed; the last return takes
    the remainder so the supplier due ends at exactly zero."""
    h = auth_headers(admin)
    body = po_body(env, "1", p1=("3", "1"), p2=("3", "3.11"))  # 12.33 gross, 1.00 discount
    po = client.post(f"{API}/orders", headers=h, json=body).json()
    client.post(f"{API}/orders/{po['id']}/approve", headers=h)
    grn = client.post(
        f"{API}/orders/{po['id']}/receive",
        headers=h,
        json={"items": [{"po_item_id": i["id"], "qty": i["qty"]} for i in po["items"]]},
    ).json()
    assert (grn["total"], due(db, env)) == ("11.33", D("11.33"))

    discounts = []
    for line in grn["items"]:
        for _ in range(3):
            res = client.post(
                f"{API}/receipts/{grn['id']}/return",
                headers=h,
                json={"items": [{"grn_item_id": line["id"], "qty": "1"}]},
            )
            assert res.status_code == 201, res.text
            discounts.append(D(res.json()["discount"]))
    assert sum(discounts) == D("1.00")
    assert due(db, env) == D("0.00")


def test_return_at_receipt_cost_when_average_differs(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    """Returning goods from a costlier receipt removes their real value (avg recomputed)."""
    h = auth_headers(admin)
    inventory.stock_in(
        db, env["p1"], env["wh"], D("10"), D("80"), "PURCHASE_IN", "TEST", None, today(), admin
    )
    grn = _received(client, h, env, discount="0")  # +10 @ 100 -> avg 90
    assert stock(db, env, "p1") == (D("20"), D("90.0000"))
    g1 = next(i for i in grn["items"] if i["product_id"] == env["p1"])
    client.post(
        f"{API}/receipts/{grn['id']}/return",
        headers=h,
        json={"items": [{"grn_item_id": g1["id"], "qty": "10"}]},
    )
    assert stock(db, env, "p1") == (D("10"), D("80.0000"))  # (1800 - 1000) / 10


def test_return_rejections(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    grn = _received(client, h, env)
    g1 = next(i for i in grn["items"] if i["product_id"] == env["p1"])
    url = f"{API}/receipts/{grn['id']}/return"

    client.post(url, headers=h, json={"items": [{"grn_item_id": g1["id"], "qty": "3"}]})
    over = client.post(url, headers=h, json={"items": [{"grn_item_id": g1["id"], "qty": "7.001"}]})
    assert over.status_code == 400 and over.json()["code"] == "OVER_RETURN"

    # goods already sold: can't return what isn't in stock any more
    inventory.stock_out(db, env["p1"], env["wh"], D("6"), SALE_OUT, "TEST", None, today(), admin)
    db.commit()  # setup is its own transaction (the failing request below rolls back its own)
    before = (counts(db), due(db, env))
    short = client.post(url, headers=h, json={"items": [{"grn_item_id": g1["id"], "qty": "2"}]})
    assert short.json()["code"] == "INSUFFICIENT_STOCK"
    assert (counts(db), due(db, env)) == before
    assert db.scalar(select(func.count()).select_from(PurchaseReturn)) == 1


# --- order lifecycle -------------------------------------------------------------------


def test_cancel_and_edit_rules(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    draft = client.post(f"{API}/orders", headers=h, json=po_body(env)).json()
    edited = client.put(
        f"{API}/orders/{draft['id']}", headers=h, json=po_body(env, "10", p1=("2", "50"))
    )
    assert edited.status_code == 200
    assert (edited.json()["subtotal"], edited.json()["total"], len(edited.json()["items"])) == (
        "100.00",
        "90.00",
        1,
    )
    assert (
        client.post(f"{API}/orders/{draft['id']}/cancel", headers=h).json()["status"] == "cancelled"
    )
    for action in ("approve", "cancel"):
        res = client.post(f"{API}/orders/{draft['id']}/{action}", headers=h)
        assert res.json()["code"] == "INVALID_STATUS"

    approved = create_approved(client, h, env)
    assert (
        client.put(f"{API}/orders/{approved['id']}", headers=h, json=po_body(env)).json()["code"]
        == "INVALID_STATUS"
    )
    assert (
        client.post(f"{API}/orders/{approved['id']}/cancel", headers=h).json()["status"]
        == "cancelled"
    )
    receive = client.post(
        f"{API}/orders/{approved['id']}/receive",
        headers=h,
        json={"items": [{"po_item_id": approved["items"][0]["id"], "qty": "1"}]},
    )
    assert receive.json()["code"] == "INVALID_STATUS"

    partial = create_approved(client, h, env)
    client.post(
        f"{API}/orders/{partial['id']}/receive",
        headers=h,
        json={"items": [{"po_item_id": partial["items"][0]["id"], "qty": "1"}]},
    )
    res = client.post(f"{API}/orders/{partial['id']}/cancel", headers=h)
    assert res.status_code == 400 and res.json()["code"] == "CANNOT_CANCEL"


def test_po_validation(client: TestClient, db: Session, admin: User, env: dict[str, int]) -> None:
    h = auth_headers(admin)
    res = client.post(f"{API}/orders", headers=h, json=po_body(env, "1200.01"))
    assert res.json()["code"] == "INVALID_DISCOUNT"
    dup = po_body(env)
    dup["items"].append(dup["items"][0])
    assert client.post(f"{API}/orders", headers=h, json=dup).json()["code"] == "DUPLICATE_LINE"
    client.post(f"/api/v1/suppliers/{env['sup']}/deactivate", headers=h)
    assert (
        client.post(f"{API}/orders", headers=h, json=po_body(env)).json()["code"]
        == "INACTIVE_SUPPLIER"
    )


# --- atomicity -------------------------------------------------------------------------


@pytest.mark.parametrize("failing", ["stock_in", "post_party_entry"])
def test_receipt_rolls_back_entirely_when_posting_fails(
    client: TestClient,
    db: Session,
    admin: User,
    env: dict[str, int],
    monkeypatch: pytest.MonkeyPatch,
    failing: str,
) -> None:
    h = auth_headers(admin)
    po = create_approved(client, h, env, discount="120")
    before = counts(db)

    if failing == "stock_in":
        real = inventory.stock_in
        calls = {"n": 0}

        def flaky(*args: object, **kwargs: object) -> object:
            calls["n"] += 1
            if calls["n"] == 2:
                raise AppError(500, "BOOM", "simulated stock failure on line 2")
            return real(*args, **kwargs)

        monkeypatch.setattr(inventory, "stock_in", flaky)
    else:

        def boom(*args: object, **kwargs: object) -> None:
            raise AppError(500, "BOOM", "simulated ledger failure")

        monkeypatch.setattr(parties, "post_party_entry", boom)

    with pytest.raises(AppError, match="simulated"):
        from app.modules.purchase import service as purchase
        from app.modules.purchase.schemas import ReceiveIn

        purchase.receive_goods(
            db,
            admin,
            po["id"],
            ReceiveIn(items=[{"po_item_id": i["id"], "qty": i["qty"]} for i in po["items"]]),
        )

    db.expire_all()
    assert counts(db) == before  # no receipt, no stock rows, no ledger rows
    assert stock(db, env, "p1")[0] == D("0")
    order = db.get(PurchaseOrder, po["id"])
    assert order is not None and order.status == "approved"
    assert all(i.received_qty == 0 for i in order.items)
    monkeypatch.undo()
    # the rolled-back receipt did not consume a number
    ok = client.post(
        f"{API}/orders/{po['id']}/receive",
        headers=h,
        json={"items": [{"po_item_id": i["id"], "qty": i["qty"]} for i in po["items"]]},
    )
    assert ok.json()["grn_number"] == "GRN-000001"


# --- permissions & audit ---------------------------------------------------------------


def test_permissions_and_audit(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    sales = db.scalar(select(User).where(User.username == "sales"))
    store = db.scalar(select(User).where(User.username == "store"))
    assert sales and store
    assert (
        client.post(f"{API}/orders", headers=auth_headers(sales), json=po_body(env)).status_code
        == 403
    )
    assert client.get(f"{API}/orders", headers=auth_headers(sales)).status_code == 403

    hs = auth_headers(store)  # Purchase/Store role: full purchase rights
    po = client.post(f"{API}/orders", headers=hs, json=po_body(env)).json()
    client.post(f"{API}/orders/{po['id']}/approve", headers=hs)
    res = client.post(
        f"{API}/orders/{po['id']}/receive",
        headers=hs,
        json={"items": [{"po_item_id": po["items"][0]["id"], "qty": "1"}]},
    )
    assert res.status_code == 201
    assert client.post(f"{API}/direct", headers=hs, json=po_body(env)).status_code == 201

    actions = set(db.scalars(select(AuditLog.entity_type + ":" + AuditLog.action)))
    assert {"purchase_order:create", "purchase_order:approve", "goods_receipt:post"} <= actions

    listed = client.get(f"{API}/orders", headers=hs, params={"status": "partially_received"}).json()
    assert [p["po_number"] for p in listed["items"]] == [po["po_number"]]
    assert client.get(f"{API}/receipts", headers=hs).json()["total"] == 2
