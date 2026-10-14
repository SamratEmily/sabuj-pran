from datetime import timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.dates import today
from app.modules.auth.models import AuditLog, User
from app.modules.master.models import Category, ExpenseCategory, Product, Unit, Warehouse
from app.modules.master.service import current_price
from tests.conftest import MakeUser, auth_headers

API = "/api/v1/master"


def _id(db: Session, model: type, **where: object) -> int:
    stmt = select(model.id)  # type: ignore[attr-defined]
    for k, v in where.items():
        stmt = stmt.where(getattr(model, k) == v)
    found = db.scalar(stmt)
    assert found is not None
    return found


def _product_payload(db: Session, **overrides: object) -> dict[str, object]:
    return {
        "name": "Test Widget",
        "category_id": _id(db, Category, name="Finished Goods"),
        "unit_id": _id(db, Unit, short_code="PCS"),
        "product_type": "trading",
        "purchase_price": "12.5",
        "reorder_level": "10",
        **overrides,
    }


# --- unique constraints ----------------------------------------------------------------


def test_unique_names_and_codes(client: TestClient, db: Session, admin: User) -> None:
    h = auth_headers(admin)

    dup_cat = client.post(f"{API}/categories", headers=h, json={"name": "raw materials"})
    assert dup_cat.status_code == 409  # case-insensitive collation
    assert dup_cat.json()["code"] == "NAME_TAKEN"

    dup_unit = client.post(f"{API}/units", headers=h, json={"name": "Kilo", "short_code": "KG"})
    assert dup_unit.json()["code"] == "SHORT_CODE_TAKEN"

    dup_wh = client.post(f"{API}/warehouses", headers=h, json={"name": "Second", "code": "MAIN"})
    assert dup_wh.json()["code"] == "CODE_TAKEN"

    dup_pm = client.post(
        f"{API}/payment-methods", headers=h, json={"name": "Cash", "method_type": "cash"}
    )
    assert dup_pm.json()["code"] == "NAME_TAKEN"

    dup_exp = client.post(f"{API}/expense-categories", headers=h, json={"name": "Rent"})
    assert dup_exp.status_code == 409

    dup_product = client.post(
        f"{API}/products", headers=h, json=_product_payload(db, name="PVC Resin")
    )
    assert dup_product.json()["code"] == "NAME_TAKEN"

    dup_code = client.post(f"{API}/products", headers=h, json=_product_payload(db, code="P-0001"))
    assert dup_code.json()["code"] == "CODE_TAKEN"

    # rename onto an existing name is also blocked
    cat_id = client.post(f"{API}/categories", headers=h, json={"name": "Spare Parts"}).json()["id"]
    clash = client.put(f"{API}/categories/{cat_id}", headers=h, json={"name": "Finished Goods"})
    assert clash.status_code == 409


# --- products --------------------------------------------------------------------------


def test_product_code_generated_and_decimals_are_strings(
    client: TestClient, db: Session, admin: User
) -> None:
    h = auth_headers(admin)
    res = client.post(f"{API}/products", headers=h, json=_product_payload(db, initial_price="99.5"))
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["code"] == "P-0007"  # seed created P-0001..P-0006
    assert body["purchase_price"] == "12.5000"
    assert body["reorder_level"] == "10.000"
    assert body["current_price"] == "99.50"
    assert body["unit_code"] == "PCS"

    # A manual code that the counter would produce next is skipped by the generator.
    manual = client.post(
        f"{API}/products", headers=h, json=_product_payload(db, name="Manual", code="P-0008")
    )
    assert manual.status_code == 201
    auto = client.post(f"{API}/products", headers=h, json=_product_payload(db, name="Auto"))
    assert auto.json()["code"] == "P-0009"

    too_precise = client.post(
        f"{API}/products", headers=h, json=_product_payload(db, name="X", initial_price="1.234")
    )
    assert too_precise.status_code == 422


def test_product_list_filters_and_search(client: TestClient, db: Session, admin: User) -> None:
    h = auth_headers(admin)
    raw = client.get(f"{API}/products", headers=h, params={"product_type": "raw_material"})
    assert raw.json()["total"] == 3
    assert all(p["current_price"] for p in raw.json()["items"])

    by_code = client.get(f"{API}/products", headers=h, params={"search": "P-0004"})
    assert [p["name"] for p in by_code.json()["items"]] == ["Water Tank 500L"]

    fg = _id(db, Category, name="Finished Goods")
    assert client.get(f"{API}/products", headers=h, params={"category_id": fg}).json()["total"] == 3


def test_product_rejects_inactive_category(client: TestClient, db: Session, admin: User) -> None:
    h = auth_headers(admin)
    cat_id = client.post(f"{API}/categories", headers=h, json={"name": "Old"}).json()["id"]
    client.post(f"{API}/categories/{cat_id}/deactivate", headers=h)
    res = client.post(f"{API}/products", headers=h, json=_product_payload(db, category_id=cat_id))
    assert res.status_code == 400
    assert res.json()["code"] == "INACTIVE_CATEGORY"


def test_sales_can_view_but_not_create_products(
    client: TestClient, db: Session, admin: User
) -> None:
    sales = db.scalar(select(User).where(User.username == "sales"))
    assert sales is not None
    h = auth_headers(sales)
    assert client.get(f"{API}/products", headers=h).status_code == 200
    assert client.post(f"{API}/products", headers=h, json=_product_payload(db)).status_code == 403


# --- price history ---------------------------------------------------------------------


def test_current_price_follows_history(client: TestClient, db: Session, admin: User) -> None:
    h = auth_headers(admin)
    pid = client.post(f"{API}/products", headers=h, json=_product_payload(db)).json()["id"]
    d = today()

    def add(price: str, day: object) -> None:
        r = client.post(
            f"{API}/products/{pid}/prices",
            headers=h,
            json={"price": price, "effective_from": str(day)},
        )
        assert r.status_code == 201, r.text

    add("120.00", d + timedelta(days=1))  # future: not yet in force
    add("100.00", d - timedelta(days=10))
    add("105.00", d)
    add("107.00", d)  # same day, entered later -> wins
    add("90.00", d - timedelta(days=30))

    assert current_price(db, pid) == Decimal("107.00")
    assert current_price(db, pid, d + timedelta(days=1)) == Decimal("120.00")
    assert current_price(db, pid, d - timedelta(days=5)) == Decimal("100.00")
    assert current_price(db, pid, d - timedelta(days=31)) is None

    history = client.get(f"{API}/products/{pid}/prices", headers=h).json()
    assert [p["price"] for p in history] == ["120.00", "107.00", "105.00", "100.00", "90.00"]
    assert [p["is_current"] for p in history] == [False, True, False, False, False]
    assert history[0]["created_by_name"] == admin.full_name

    listed = client.get(f"{API}/prices", headers=h, params={"search": "Test Widget"}).json()
    assert listed["items"][0]["current_price"] == "107.00"
    assert listed["items"][0]["price_effective_from"] == str(d)

    # default effective date is today; old rows are never modified
    r = client.post(f"{API}/products/{pid}/prices", headers=h, json={"price": "110"})
    assert r.json()["effective_from"] == str(d) and r.json()["is_current"] is True
    assert len(client.get(f"{API}/products/{pid}/prices", headers=h).json()) == 6
    assert (
        db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.entity_type == "product_price")
        )
        == 6
    )


# --- warehouses ------------------------------------------------------------------------


def _defaults(db: Session) -> list[str]:
    db.expire_all()
    return list(db.scalars(select(Warehouse.code).where(Warehouse.is_default.is_(True))))


def test_exactly_one_default_warehouse(client: TestClient, db: Session, admin: User) -> None:
    h = auth_headers(admin)
    assert _defaults(db) == ["MAIN"]
    main_id = _id(db, Warehouse, code="MAIN")

    second = client.post(
        f"{API}/warehouses", headers=h, json={"name": "Depot", "code": "DEP", "is_default": True}
    )
    assert second.status_code == 201
    assert _defaults(db) == ["DEP"]

    third = client.post(f"{API}/warehouses", headers=h, json={"name": "Yard", "code": "YRD"})
    assert third.json()["is_default"] is False
    assert _defaults(db) == ["DEP"]

    # switching back through update
    back = client.put(
        f"{API}/warehouses/{main_id}",
        headers=h,
        json={"name": "Main Warehouse", "code": "MAIN", "is_default": True},
    )
    assert back.status_code == 200
    assert _defaults(db) == ["MAIN"]

    # the default can't be unset directly or deactivated
    unset = client.put(
        f"{API}/warehouses/{main_id}",
        headers=h,
        json={"name": "Main Warehouse", "code": "MAIN", "is_default": False},
    )
    assert unset.json()["code"] == "DEFAULT_REQUIRED"
    deact = client.post(f"{API}/warehouses/{main_id}/deactivate", headers=h)
    assert deact.json()["code"] == "DEFAULT_WAREHOUSE"

    # an inactive warehouse can't become the default
    yard = third.json()["id"]
    client.post(f"{API}/warehouses/{yard}/deactivate", headers=h)
    res = client.put(
        f"{API}/warehouses/{yard}",
        headers=h,
        json={"name": "Yard", "code": "YRD", "is_default": True},
    )
    assert res.json()["code"] == "INACTIVE_DEFAULT"
    assert _defaults(db) == ["MAIN"]


def test_warehouse_with_stock_cannot_be_deactivated(
    client: TestClient, db: Session, admin: User
) -> None:
    from app.modules.inventory import service as inventory
    from app.modules.inventory.models import ADJUST_OUT, PURCHASE_IN

    h = auth_headers(admin)
    depot = client.post(f"{API}/warehouses", headers=h, json={"name": "Depot", "code": "DEP"})
    wh = depot.json()["id"]
    product = _id(db, Product, code="P-0001")
    inventory.stock_in(db, product, wh, Decimal("2"), Decimal("10"), PURCHASE_IN, "T", None,
                       today(), admin)  # fmt: skip
    res = client.post(f"{API}/warehouses/{wh}/deactivate", headers=h)
    assert res.json()["code"] == "WAREHOUSE_HAS_STOCK"
    assert db.get(Warehouse, wh).is_active  # type: ignore[union-attr]

    inventory.stock_out(db, product, wh, Decimal("2"), ADJUST_OUT, "T", None, today(), admin)
    res = client.post(f"{API}/warehouses/{wh}/deactivate", headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["is_active"] is False


def test_first_warehouse_becomes_default(
    client: TestClient, db: Session, make_user: MakeUser
) -> None:
    user = make_user("wh", ["warehouse.create"])
    res = client.post(
        f"{API}/warehouses", headers=auth_headers(user), json={"name": "Only", "code": "ONE"}
    )
    assert res.json()["is_default"] is True


# --- deactivation of used reference data -----------------------------------------------


def test_deactivating_used_unit_needs_confirmation(
    client: TestClient, db: Session, admin: User
) -> None:
    h = auth_headers(admin)
    kg = _id(db, Unit, short_code="KG")

    first = client.post(f"{API}/units/{kg}/deactivate", headers=h)
    assert first.status_code == 409
    assert first.json()["code"] == "CONFIRM_REQUIRED"
    assert "2 active product(s)" in first.json()["detail"]
    assert db.get(Unit, kg).is_active is True  # type: ignore[union-attr]

    forced = client.post(f"{API}/units/{kg}/deactivate", headers=h, params={"force": True})
    assert forced.status_code == 200
    assert forced.json()["is_active"] is False
    # products keep their unit
    assert db.scalar(select(func.count()).select_from(Product).where(Product.unit_id == kg)) == 2

    unused = client.post(f"{API}/units", headers=h, json={"name": "Dozen", "short_code": "DZ"})
    ok = client.post(f"{API}/units/{unused.json()['id']}/deactivate", headers=h)
    assert ok.status_code == 200
    actions = db.scalars(
        select(AuditLog.action).where(AuditLog.entity_type == "unit").order_by(AuditLog.id)
    ).all()
    assert actions == ["deactivate", "create", "deactivate"]


# --- lookups ---------------------------------------------------------------------------


def test_lookups_return_active_items_for_any_user(
    client: TestClient, db: Session, admin: User, make_user: MakeUser
) -> None:
    h = auth_headers(admin)
    misc = _id(db, ExpenseCategory, name="Misc")
    client.post(f"{API}/expense-categories/{misc}/deactivate", headers=h)

    nobody = make_user("plain")  # no permissions at all
    res = client.get(f"{API}/lookups", headers=auth_headers(nobody))
    assert res.status_code == 200
    data = res.json()
    assert [w["code"] for w in data["warehouses"]] == ["MAIN"]
    assert data["warehouses"][0]["is_default"] is True
    assert "Misc" not in [c["name"] for c in data["expense_categories"]]
    assert {m["method_type"] for m in data["payment_methods"]} == {"cash", "bank", "mfs", "online"}
    assert len(data["units"]) == 6

    assert client.get(f"{API}/lookups").status_code == 401


def test_unchanged_product_save_is_not_audited(
    client: TestClient, db: Session, admin: User
) -> None:
    """Decimals must reach services as Decimal (not strings) so change detection works."""
    h = auth_headers(admin)
    product = client.post(f"{API}/products", headers=h, json=_product_payload(db)).json()
    same = {
        k: product[k]
        for k in (
            "code",
            "name",
            "category_id",
            "unit_id",
            "product_type",
            "purchase_price",
            "reorder_level",
            "description",
        )
    }
    assert client.put(f"{API}/products/{product['id']}", headers=h, json=same).status_code == 200
    updates = db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.entity_type == "product", AuditLog.action == "update")
    )
    assert updates == 0
