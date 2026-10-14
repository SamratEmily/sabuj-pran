"""Stock documents (transfers, adjustments, counts) and the stock / ledger endpoints."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.dates import today
from app.core.errors import AppError
from app.modules.auth.models import AuditLog, User
from app.modules.inventory import service as inv
from app.modules.inventory.models import (
    PURCHASE_IN,
    StockBalance,
    StockTransaction,
    StockTransfer,
)
from app.modules.master.models import Product, Warehouse
from tests.conftest import auth_headers

API = "/api/v1/inventory"
D = Decimal


@pytest.fixture
def ids(db: Session, admin: User) -> dict[str, int]:
    products = dict(db.execute(select(Product.code, Product.id)).all())
    main = db.scalar(select(Warehouse.id).where(Warehouse.code == "MAIN"))
    second = Warehouse(name="Second", code="WH2", address="", is_default=False, is_active=True)
    db.add(second)
    db.flush()
    assert main is not None
    return {
        "p1": products["P-0001"],
        "p2": products["P-0002"],
        "p3": products["P-0003"],
        "wh1": main,
        "wh2": second.id,
    }


def receive(
    db: Session, user: User, product: int, wh: int, qty: str, cost: str, when: date | None = None
) -> None:
    inv.stock_in(db, product, wh, D(qty), D(cost), PURCHASE_IN, "TEST", None, when or today(), user)


def balance(db: Session, product: int, wh: int) -> tuple[Decimal, Decimal, Decimal]:
    b = inv.get_balance(db, product, wh)
    return (b.qty_on_hand, b.qty_reserved, b.avg_cost) if b else (D("0"), D("0"), D("0"))


def stock_rows(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(StockTransaction)) or 0


# --- transfers -------------------------------------------------------------------------


def test_transfer_document_create_post_and_double_post(
    client: TestClient, db: Session, admin: User, ids: dict[str, int]
) -> None:
    h = auth_headers(admin)
    receive(db, admin, ids["p1"], ids["wh1"], "10", "50")
    receive(db, admin, ids["p2"], ids["wh1"], "6", "20")

    res = client.post(
        f"{API}/transfers",
        headers=h,
        json={
            "from_warehouse_id": ids["wh1"],
            "to_warehouse_id": ids["wh2"],
            "items": [
                {"product_id": ids["p1"], "qty": "4"},
                {"product_id": ids["p2"], "qty": "1.5"},
            ],
        },
    )
    assert res.status_code == 201, res.text
    doc = res.json()
    assert (doc["number"], doc["status"]) == ("TRF-000001", "draft")
    assert balance(db, ids["p1"], ids["wh1"])[0] == D("10")  # nothing moves until posted

    posted = client.post(f"{API}/transfers/{doc['id']}/post", headers=h)
    assert posted.status_code == 200, posted.text
    body = posted.json()
    assert body["status"] == "posted" and body["posted_by_name"] == admin.full_name
    assert [i["unit_cost"] for i in body["items"]] == ["50.0000", "20.0000"]
    assert balance(db, ids["p1"], ids["wh1"])[0] == D("6")
    assert balance(db, ids["p1"], ids["wh2"]) == (D("4"), D("0"), D("50.0000"))
    assert balance(db, ids["p2"], ids["wh2"])[0] == D("1.5")

    again = client.post(f"{API}/transfers/{doc['id']}/post", headers=h)
    assert again.status_code == 400 and again.json()["code"] == "ALREADY_POSTED"
    assert balance(db, ids["p1"], ids["wh2"])[0] == D("4")  # not moved twice
    cancel = client.post(f"{API}/transfers/{doc['id']}/cancel", headers=h)
    assert cancel.json()["code"] == "ALREADY_POSTED"

    actions = db.scalars(
        select(AuditLog.action)
        .where(AuditLog.entity_type == "stock_transfer")
        .order_by(AuditLog.id)
    ).all()
    assert actions == ["create", "post"]


def test_transfer_rolls_back_completely_when_a_line_fails(
    client: TestClient,
    db: Session,
    admin: User,
    ids: dict[str, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receive(db, admin, ids["p1"], ids["wh1"], "10", "50")
    receive(db, admin, ids["p2"], ids["wh1"], "10", "20")
    doc = inv.create_transfer(
        db,
        admin,
        inv.TransferIn(
            from_warehouse_id=ids["wh1"],
            to_warehouse_id=ids["wh2"],
            items=[{"product_id": ids["p1"], "qty": "4"}, {"product_id": ids["p2"], "qty": "3"}],
        ),
    )
    before = {
        k: balance(db, ids[p], ids[w])
        for k, (p, w) in {
            "a": ("p1", "wh1"),
            "b": ("p2", "wh1"),
            "c": ("p1", "wh2"),
            "d": ("p2", "wh2"),
        }.items()
    }
    rows_before = stock_rows(db)

    real_stock_in = inv.stock_in
    calls = {"n": 0}

    def flaky_stock_in(*args: object, **kwargs: object) -> object:
        calls["n"] += 1
        if calls["n"] == 2:  # second line's IN fails after its OUT and the whole first line
            raise AppError(500, "BOOM", "simulated failure mid-transfer")
        return real_stock_in(*args, **kwargs)

    monkeypatch.setattr(inv, "stock_in", flaky_stock_in)
    with pytest.raises(AppError, match="simulated"):
        inv.post_transfer(db, doc.id, admin)

    db.expire_all()
    after = {
        k: balance(db, ids[p], ids[w])
        for k, (p, w) in {
            "a": ("p1", "wh1"),
            "b": ("p2", "wh1"),
            "c": ("p1", "wh2"),
            "d": ("p2", "wh2"),
        }.items()
    }
    assert after == before
    assert stock_rows(db) == rows_before
    header = db.get(StockTransfer, doc.id)
    assert header is not None and header.status == "draft" and header.posted_at is None
    assert all(i.unit_cost is None for i in header.items)

    monkeypatch.setattr(inv, "stock_in", real_stock_in)
    inv.post_transfer(db, doc.id, admin)  # the same draft posts fine afterwards
    assert balance(db, ids["p2"], ids["wh2"])[0] == D("3")


def test_posting_rechecks_master_data_deactivated_after_the_draft(
    client: TestClient, db: Session, admin: User, ids: dict[str, int]
) -> None:
    h = auth_headers(admin)
    receive(db, admin, ids["p1"], ids["wh1"], "10", "50")
    draft = client.post(
        f"{API}/transfers",
        headers=h,
        json={
            "from_warehouse_id": ids["wh1"],
            "to_warehouse_id": ids["wh2"],
            "items": [{"product_id": ids["p1"], "qty": "4"}],
        },
    ).json()
    count = client.post(
        f"{API}/counts",
        headers=h,
        json={"warehouse_id": ids["wh1"], "items": [{"product_id": ids["p1"], "counted_qty": "9"}]},
    ).json()
    before = stock_rows(db)
    db.get(Warehouse, ids["wh2"]).is_active = False  # type: ignore[union-attr]
    db.flush()
    res = client.post(f"{API}/transfers/{draft['id']}/post", headers=h)
    assert res.json()["code"] == "INACTIVE_WAREHOUSE"

    db.get(Product, ids["p1"]).is_active = False  # type: ignore[union-attr]
    db.flush()
    res = client.post(f"{API}/counts/{count['id']}/post", headers=h)
    assert res.json()["code"] == "INACTIVE_PRODUCT"
    assert stock_rows(db) == before


def test_transfer_validation(
    client: TestClient, db: Session, admin: User, ids: dict[str, int]
) -> None:
    h = auth_headers(admin)
    same = client.post(
        f"{API}/transfers",
        headers=h,
        json={
            "from_warehouse_id": ids["wh1"],
            "to_warehouse_id": ids["wh1"],
            "items": [{"product_id": ids["p1"], "qty": "1"}],
        },
    )
    assert same.json()["code"] == "SAME_WAREHOUSE"
    dup = client.post(
        f"{API}/transfers",
        headers=h,
        json={
            "from_warehouse_id": ids["wh1"],
            "to_warehouse_id": ids["wh2"],
            "items": [{"product_id": ids["p1"], "qty": "1"}, {"product_id": ids["p1"], "qty": "2"}],
        },
    )
    assert dup.json()["code"] == "DUPLICATE_LINE"
    zero = client.post(
        f"{API}/transfers",
        headers=h,
        json={
            "from_warehouse_id": ids["wh1"],
            "to_warehouse_id": ids["wh2"],
            "items": [{"product_id": ids["p1"], "qty": "0"}],
        },
    )
    assert zero.status_code == 422

    # posting more than is free fails and leaves the draft untouched
    receive(db, admin, ids["p1"], ids["wh1"], "2", "5")
    doc = client.post(
        f"{API}/transfers",
        headers=h,
        json={
            "from_warehouse_id": ids["wh1"],
            "to_warehouse_id": ids["wh2"],
            "items": [{"product_id": ids["p1"], "qty": "3"}],
        },
    ).json()
    res = client.post(f"{API}/transfers/{doc['id']}/post", headers=h)
    assert res.json()["code"] == "INSUFFICIENT_STOCK"
    assert client.get(f"{API}/transfers/{doc['id']}", headers=h).json()["status"] == "draft"

    cancelled = client.post(f"{API}/transfers/{doc['id']}/cancel", headers=h)
    assert cancelled.json()["status"] == "cancelled"
    res = client.post(f"{API}/transfers/{doc['id']}/post", headers=h)
    assert res.json()["code"] == "INVALID_STATUS"


# --- adjustments -----------------------------------------------------------------------


def test_adjustment_create_then_finalize(
    client: TestClient, db: Session, admin: User, ids: dict[str, int]
) -> None:
    h = auth_headers(admin)
    receive(db, admin, ids["p1"], ids["wh1"], "10", "40")
    res = client.post(
        f"{API}/adjustments",
        headers=h,
        json={
            "warehouse_id": ids["wh1"],
            "reason": "Damaged and found stock",
            "items": [
                {"product_id": ids["p1"], "direction": "decrease", "qty": "2"},
                {"product_id": ids["p2"], "direction": "increase", "qty": "5", "unit_cost": "12.5"},
                # never stocked, no cost given -> product purchase_price (Packing Film: 850.0000)
                {"product_id": ids["p3"], "direction": "increase", "qty": "1"},
            ],
        },
    )
    assert res.status_code == 201, res.text
    doc = res.json()
    assert (doc["number"], doc["status"]) == ("ADJ-000001", "draft")
    assert balance(db, ids["p1"], ids["wh1"])[0] == D("10")  # create posts nothing

    posted = client.post(f"{API}/adjustments/{doc['id']}/post", headers=h).json()
    assert posted["status"] == "posted"
    assert [i["unit_cost"] for i in posted["items"]] == ["40.0000", "12.5000", "850.0000"]
    assert balance(db, ids["p1"], ids["wh1"]) == (D("8"), D("0"), D("40.0000"))
    assert balance(db, ids["p2"], ids["wh1"]) == (D("5"), D("0"), D("12.5000"))
    assert balance(db, ids["p3"], ids["wh1"]) == (D("1"), D("0"), D("850.0000"))
    types = db.scalars(
        select(StockTransaction.txn_type).where(StockTransaction.ref_type == "STOCK_ADJUSTMENT")
    ).all()
    assert sorted(types) == ["ADJUST_IN", "ADJUST_IN", "ADJUST_OUT"]

    again = client.post(f"{API}/adjustments/{doc['id']}/post", headers=h)
    assert again.json()["code"] == "ALREADY_POSTED"


def test_adjustment_cannot_take_reserved_stock(
    client: TestClient, db: Session, admin: User, ids: dict[str, int]
) -> None:
    h = auth_headers(admin)
    receive(db, admin, ids["p1"], ids["wh1"], "10", "40")
    inv.reserve(db, ids["p1"], ids["wh1"], D("8"))
    doc = client.post(
        f"{API}/adjustments",
        headers=h,
        json={
            "warehouse_id": ids["wh1"],
            "reason": "Shrinkage",
            "items": [{"product_id": ids["p1"], "direction": "decrease", "qty": "3"}],
        },
    ).json()
    res = client.post(f"{API}/adjustments/{doc['id']}/post", headers=h)
    assert res.status_code == 400 and res.json()["code"] == "INSUFFICIENT_STOCK"
    assert balance(db, ids["p1"], ids["wh1"]) == (D("10"), D("8"), D("40.0000"))
    assert client.get(f"{API}/adjustments/{doc['id']}", headers=h).json()["status"] == "draft"


def test_pending_adjustment_only_posts_through_finalize(
    db: Session, admin: User, ids: dict[str, int]
) -> None:
    """The approvals module will finalize pending adjustments; the plain post path refuses."""
    receive(db, admin, ids["p1"], ids["wh1"], "5", "10")
    doc = inv.create_adjustment(
        db,
        admin,
        inv.AdjustmentIn(
            warehouse_id=ids["wh1"],
            reason="Approval test",
            items=[{"product_id": ids["p1"], "direction": "decrease", "qty": "1"}],
        ),
    )
    doc.status = "pending_approval"
    db.commit()
    with pytest.raises(AppError) as err:
        inv.finalize_adjustment(db, doc.id, admin)
    assert err.value.code == "INVALID_STATUS"
    inv.finalize_adjustment(db, doc.id, admin, allowed=("pending_approval",))
    assert balance(db, ids["p1"], ids["wh1"])[0] == D("4")


# --- physical counts -------------------------------------------------------------------


def test_count_posts_variances(
    client: TestClient, db: Session, admin: User, ids: dict[str, int]
) -> None:
    h = auth_headers(admin)
    receive(db, admin, ids["p1"], ids["wh1"], "10", "30")
    receive(db, admin, ids["p2"], ids["wh1"], "5", "8")
    res = client.post(
        f"{API}/counts",
        headers=h,
        json={
            "warehouse_id": ids["wh1"],
            "items": [
                {"product_id": ids["p1"], "counted_qty": "7"},  # -3
                {"product_id": ids["p2"], "counted_qty": "8"},  # +3 at current avg
                {
                    "product_id": ids["p3"],
                    "counted_qty": "2",
                },  # +2, never stocked -> purchase price
            ],
        },
    )
    assert res.status_code == 201, res.text
    doc = res.json()
    assert doc["number"] == "CNT-000001"
    assert [(i["system_qty"], i["variance"]) for i in doc["items"]] == [
        ("10.000", "-3.000"),
        ("5.000", "3.000"),
        ("0.000", "2.000"),
    ]

    # stock moves after the snapshot: the variance is still applied as a delta
    receive(db, admin, ids["p1"], ids["wh1"], "1", "30")
    detail = client.get(f"{API}/counts/{doc['id']}", headers=h).json()
    assert detail["items"][0]["current_qty"] == "11.000"

    posted = client.post(f"{API}/counts/{doc['id']}/post", headers=h).json()
    assert posted["status"] == "posted"
    assert posted["moved_since_snapshot"] == [ids["p1"]]
    assert balance(db, ids["p1"], ids["wh1"])[0] == D("8")  # 11 - 3
    assert balance(db, ids["p2"], ids["wh1"]) == (D("8"), D("0"), D("8.0000"))
    assert balance(db, ids["p3"], ids["wh1"]) == (D("2"), D("0"), D("850.0000"))
    rows = db.execute(
        select(StockTransaction.txn_type, StockTransaction.qty_in, StockTransaction.qty_out)
        .where(StockTransaction.ref_type == "STOCK_COUNT")
        .order_by(StockTransaction.id)
    ).all()
    assert [tuple(r) for r in rows] == [
        ("COUNT_OUT", D("0"), D("3")),
        ("COUNT_IN", D("3"), D("0")),
        ("COUNT_IN", D("2"), D("0")),
    ]

    again = client.post(f"{API}/counts/{doc['id']}/post", headers=h)
    assert again.json()["code"] == "ALREADY_POSTED"
    assert balance(db, ids["p1"], ids["wh1"])[0] == D("8")


def test_count_out_cannot_take_reserved_stock(
    db: Session, admin: User, ids: dict[str, int]
) -> None:
    receive(db, admin, ids["p1"], ids["wh1"], "10", "30")
    inv.reserve(db, ids["p1"], ids["wh1"], D("9"))
    doc = inv.create_count(
        db,
        admin,
        inv.CountIn(warehouse_id=ids["wh1"], items=[{"product_id": ids["p1"], "counted_qty": "8"}]),
    )
    with pytest.raises(AppError) as err:
        inv.post_count(db, doc.id, admin)
    assert err.value.code == "INSUFFICIENT_STOCK"
    assert balance(db, ids["p1"], ids["wh1"])[:2] == (D("10"), D("9"))


# --- permissions -----------------------------------------------------------------------


def test_permissions(client: TestClient, db: Session, admin: User, ids: dict[str, int]) -> None:
    sales = db.scalar(select(User).where(User.username == "sales"))
    store = db.scalar(select(User).where(User.username == "store"))
    assert sales and store
    body = {
        "from_warehouse_id": ids["wh1"],
        "to_warehouse_id": ids["wh2"],
        "items": [{"product_id": ids["p1"], "qty": "1"}],
    }
    assert (
        client.post(f"{API}/transfers", headers=auth_headers(sales), json=body).status_code == 403
    )
    assert client.get(f"{API}/stock", headers=auth_headers(sales)).status_code == 200
    assert (
        client.post(f"{API}/transfers", headers=auth_headers(store), json=body).status_code == 201
    )


# --- stock list & ledger ---------------------------------------------------------------


def test_stock_list_filters_and_value(
    client: TestClient, db: Session, admin: User, ids: dict[str, int]
) -> None:
    h = auth_headers(admin)
    receive(db, admin, ids["p1"], ids["wh1"], "10", "12.5")
    receive(db, admin, ids["p1"], ids["wh2"], "4", "10")
    receive(db, admin, ids["p2"], ids["wh1"], "3", "100")
    inv.reserve(db, ids["p1"], ids["wh1"], D("2"))
    db.get(Product, ids["p2"]).reorder_level = D("5")  # type: ignore[union-attr]
    db.flush()

    all_rows = client.get(f"{API}/stock", headers=h).json()
    assert all_rows["total"] == 3
    assert all_rows["total_value"] == "465.00"  # 125 + 40 + 300
    row = next(
        r
        for r in all_rows["items"]
        if r["product_id"] == ids["p1"] and r["warehouse_id"] == ids["wh1"]
    )
    assert (row["qty_on_hand"], row["qty_reserved"], row["qty_available"], row["value"]) == (
        "10.000",
        "2.000",
        "8.000",
        "125.00",
    )

    one = client.get(
        f"{API}/stock", headers=h, params={"product_id": ids["p1"], "warehouse_id": ids["wh1"]}
    ).json()
    assert [(r["product_id"], r["qty_available"]) for r in one["items"]] == [(ids["p1"], "8.000")]
    wh2 = client.get(f"{API}/stock", headers=h, params={"warehouse_id": ids["wh2"]}).json()
    assert [(r["product_id"], r["value"]) for r in wh2["items"]] == [(ids["p1"], "40.00")]
    assert wh2["total_value"] == "40.00"

    low = client.get(f"{API}/stock", headers=h, params={"low_stock": True}).json()
    assert [r["product_id"] for r in low["items"]] == [ids["p2"]]
    assert low["items"][0]["is_low"] is True

    raw = client.get(
        f"{API}/stock", headers=h, params={"product_type": "raw_material", "search": "P-0002"}
    ).json()
    assert [r["product_id"] for r in raw["items"]] == [ids["p2"]]
    assert (
        client.get(f"{API}/stock", headers=h, params={"product_type": "finished_good"}).json()[
            "total"
        ]
        == 0
    )

    valuation = db.execute(
        select(func.sum(StockBalance.qty_on_hand * StockBalance.avg_cost))
    ).scalar()
    assert D(valuation).quantize(D("0.01")) == D("465.00")
    view_total = db.execute(text("SELECT SUM(value) FROM v_stock_valuation")).scalar()
    assert view_total == D("465.00")


def test_ledger_opening_and_running_balance_across_pages(
    client: TestClient, db: Session, admin: User, ids: dict[str, int]
) -> None:
    h = auth_headers(admin)
    p, w1, w2 = ids["p1"], ids["wh1"], ids["wh2"]
    base = date(2026, 3, 1)
    receive(db, admin, p, w1, "10", "5", base)  # before range
    receive(db, admin, p, w2, "4", "5", base + timedelta(days=1))  # before range, other wh
    receive(db, admin, p, w1, "6", "5", base + timedelta(days=5))
    inv.stock_out(db, p, w1, D("3"), "SALE_OUT", "TEST", None, base + timedelta(days=6), admin)
    inv.transfer(db, p, w1, w2, D("2"), "TEST", None, base + timedelta(days=7), admin)
    receive(db, admin, p, w2, "1", "5", base + timedelta(days=30))  # after range

    params = {"product_id": p, "from": "2026-03-04", "to": "2026-03-20", "page_size": 2}
    page1 = client.get(f"{API}/ledger", headers=h, params=params).json()
    assert page1["opening_balance"] == "14.000"  # 10 + 4 across both warehouses
    assert page1["closing_balance"] == "17.000"  # whole range, not just this page
    assert page1["total"] == 4
    assert [r["running_balance"] for r in page1["items"]] == ["20.000", "17.000"]
    page2 = client.get(f"{API}/ledger", headers=h, params={**params, "page": 2}).json()
    # transfer OUT then IN on the same day: all-warehouse balance dips and returns
    assert [r["running_balance"] for r in page2["items"]] == ["15.000", "17.000"]
    assert [r["txn_type"] for r in page2["items"]] == ["TRANSFER_OUT", "TRANSFER_IN"]

    one_wh = client.get(
        f"{API}/ledger", headers=h, params={"product_id": p, "warehouse_id": w1}
    ).json()
    # single warehouse, no range: running balance == stored balance_after on every row
    assert all(r["running_balance"] == r["balance_after"] for r in one_wh["items"])
    assert one_wh["items"][-1]["running_balance"] == "11.000" == f"{balance(db, p, w1)[0]:.3f}"

    full = client.get(f"{API}/ledger", headers=h, params={"product_id": p, "page_size": 100}).json()
    total_on_hand = balance(db, p, w1)[0] + balance(db, p, w2)[0]
    assert D(full["items"][-1]["running_balance"]) == total_on_hand == D("18")

    missing = client.get(f"{API}/ledger", headers=h)
    assert missing.status_code == 422  # product_id is required
