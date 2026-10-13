"""Approvals: rules, pending documents post nothing, approve posts exactly once, reject,
self-approval / wrong role / double decisions, and the module retrofits."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.dates import today
from app.modules.approvals import service as approvals
from app.modules.approvals.models import Approval
from app.modules.approvals.schemas import RuleIn
from app.modules.auth.models import Role, User
from app.modules.inventory import service as inventory
from app.modules.inventory.models import PURCHASE_IN, StockTransaction
from app.modules.master.models import ExpenseCategory, Product, Warehouse
from app.modules.money import service as money
from app.modules.money.models import MoneyAccount, MoneyTransaction
from app.modules.parties import service as parties
from app.modules.parties.models import SUPPLIER, PartyLedger
from app.modules.parties.schemas import PartyIn
from tests.conftest import MakeUser, auth_headers

API = "/api/v1/approvals"
D = Decimal


@pytest.fixture
def env(db: Session, admin: User) -> dict[str, int]:
    accounts = dict(db.execute(select(MoneyAccount.name, MoneyAccount.id)).all())
    products = dict(db.execute(select(Product.code, Product.id)).all())
    roles = dict(db.execute(select(Role.name, Role.id)).all())
    users = dict(db.execute(select(User.username, User.id)).all())
    supplier = parties.create_party(
        db, admin, parties.SUPPLIERS, PartyIn(name="Plastic Mills", opening_due=D("50000"))
    )
    wh = db.scalar(select(Warehouse.id).where(Warehouse.code == "MAIN"))
    rent = db.scalar(select(ExpenseCategory.id).where(ExpenseCategory.name == "Rent"))
    assert wh and rent
    money.money_in(db, accounts["Cash in Hand"], D("20000"), "INCOME", "TEST", None, today(), admin)
    db.commit()
    return {
        "cash": accounts["Cash in Hand"],
        "p1": products["P-0001"],
        "wh": wh,
        "rent": rent,
        "sup": supplier.id,
        "owner_role": roles["Owner"],
        "accounts_role": roles["Accounts"],
        "owner": users["owner"],
    }


def add_rule(db: Session, admin: User, document_type: str, amount: str, role_id: int) -> None:
    approvals.create_rule(
        db,
        admin,
        RuleIn(document_type=document_type, min_amount=D(amount), approver_role_id=role_id),
    )


def user(db: Session, user_id: int) -> User:
    found = db.get(User, user_id)
    assert found is not None
    return found


def snapshot(db: Session, env: dict[str, int]) -> tuple:
    """Everything a posting could touch."""
    db.expire_all()
    count = lambda model: db.scalar(select(func.count()).select_from(model)) or 0  # noqa: E731
    cash = db.get(MoneyAccount, env["cash"])
    stock = inventory.get_balance(db, env["p1"], env["wh"])
    return (
        cash.balance if cash else None,
        count(MoneyTransaction),
        count(PartyLedger),
        count(StockTransaction),
        stock.qty_on_hand if stock else D("0"),
        parties.get_balance(db, SUPPLIER, env["sup"]),
    )


def expense(client: TestClient, h: dict, env: dict[str, int], amount: str) -> dict:
    res = client.post(
        "/api/v1/money/expenses",
        headers=h,
        json={"expense_category_id": env["rent"], "account_id": env["cash"], "amount": amount},
    )
    assert res.status_code == 201, res.text
    return res.json()


def pending(db: Session) -> list[Approval]:
    db.expire_all()
    return list(db.scalars(select(Approval).where(Approval.status == "pending")))


# --- thresholds ------------------------------------------------------------------------


def test_below_threshold_posts_immediately(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    add_rule(db, admin, "EXPENSE", "10000", env["owner_role"])
    add_rule(db, admin, "PURCHASE_ORDER", "50000", env["owner_role"])
    h = auth_headers(admin)
    exp = expense(client, h, env, "9999.99")
    assert exp["status"] == "posted"
    pay = client.post(  # no SUPPLIER_PAYMENT rule at all
        "/api/v1/money/supplier-payments",
        headers=h,
        json={"supplier_id": env["sup"], "account_id": env["cash"], "amount": "5000"},
    ).json()
    assert pay["status"] == "posted"
    po = client.post(
        "/api/v1/purchase/orders",
        headers=h,
        json={
            "supplier_id": env["sup"],
            "warehouse_id": env["wh"],
            "items": [{"product_id": env["p1"], "qty": "10", "unit_cost": "100"}],
        },
    ).json()
    assert client.post(f"/api/v1/purchase/orders/{po['id']}/approve", headers=h).json()[
        "status"
    ] == ("approved")
    assert pending(db) == []
    assert snapshot(db, env)[0] == D("5000.01")


def test_expense_above_threshold_posts_nothing_until_approved_then_exactly_once(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    add_rule(db, admin, "EXPENSE", "10000", env["owner_role"])
    before = snapshot(db, env)
    exp = expense(client, auth_headers(admin), env, "12000")
    assert exp["status"] == "pending_approval"
    assert snapshot(db, env) == before  # no money moved, no ledger rows

    owner = auth_headers(user(db, env["owner"]))
    assert client.get(f"{API}/pending/count", headers=owner).json() == {"count": 1}
    listed = client.get(f"{API}/pending", headers=owner).json()["items"]
    assert [(a["document_number"], a["amount"], a["can_decide"]) for a in listed] == [
        (exp["number"], "12000.00", True)
    ]

    res = client.post(f"{API}/{listed[0]['id']}/approve", headers=owner, json={"remark": "ok"})
    assert res.status_code == 200, res.text
    assert (res.json()["status"], res.json()["decided_by_name"]) == ("approved", "Business Owner")
    voucher = client.get(f"/api/v1/money/expenses/{exp['id']}", headers=owner).json()
    assert voucher["status"] == "posted"
    assert snapshot(db, env)[:2] == (D("8000.00"), before[1] + 1)

    again = client.post(f"{API}/{listed[0]['id']}/approve", headers=owner, json={})
    assert again.json()["code"] == "ALREADY_DECIDED"
    assert snapshot(db, env)[:2] == (D("8000.00"), before[1] + 1)  # posted exactly once
    assert client.get(f"{API}/pending/count", headers=owner).json() == {"count": 0}


def test_supplier_payment_pending_leaves_party_ledger_alone(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    add_rule(db, admin, "SUPPLIER_PAYMENT", "1000", env["owner_role"])
    before = snapshot(db, env)
    pay = client.post(
        "/api/v1/money/supplier-payments",
        headers=auth_headers(admin),
        json={"supplier_id": env["sup"], "account_id": env["cash"], "amount": "3000"},
    ).json()
    assert pay["status"] == "pending_approval"
    assert snapshot(db, env) == before
    approval = pending(db)[0]
    res = client.post(
        f"{API}/{approval.id}/approve", headers=auth_headers(user(db, env["owner"])), json={}
    )
    assert res.status_code == 200, res.text
    after = snapshot(db, env)
    assert (after[0], after[5]) == (D("17000.00"), D("47000.00"))
    assert after[2] == before[2] + 1


def test_highest_matching_rule_wins(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    add_rule(db, admin, "EXPENSE", "1000", env["accounts_role"])
    add_rule(db, admin, "EXPENSE", "5000", env["owner_role"])
    expense(client, auth_headers(admin), env, "6000")
    expense(client, auth_headers(admin), env, "2000")
    expense(client, auth_headers(admin), env, "500")  # below both: posted
    roles = sorted((a.amount, a.approver_role_id) for a in pending(db))
    assert roles == [(D("2000.00"), env["accounts_role"]), (D("6000.00"), env["owner_role"])]


# --- who may decide --------------------------------------------------------------------


def test_self_approval_wrong_role_and_admin(
    client: TestClient, db: Session, admin: User, env: dict[str, int], make_user: MakeUser
) -> None:
    add_rule(db, admin, "EXPENSE", "10000", env["owner_role"])
    clerk = make_user(permissions=["expense.create", "expense.view", "approval.approve"])
    expense(client, auth_headers(clerk), env, "11000")
    approval = pending(db)[0]
    before = snapshot(db, env)

    mine = client.post(f"{API}/{approval.id}/approve", headers=auth_headers(clerk), json={})
    assert (mine.status_code, mine.json()["code"]) == (403, "SELF_APPROVAL")
    other = make_user(permissions=["approval.approve", "approval.view"])
    wrong = client.post(f"{API}/{approval.id}/approve", headers=auth_headers(other), json={})
    assert (wrong.status_code, wrong.json()["code"]) == (403, "WRONG_ROLE")
    assert "Owner" in wrong.json()["detail"]
    no_perm = make_user(permissions=["approval.view"])
    assert (
        client.post(f"{API}/{approval.id}/approve", headers=auth_headers(no_perm)).status_code
        == 403
    )
    assert snapshot(db, env) == before

    # Admin may approve anyone's request (but not their own)
    res = client.post(f"{API}/{approval.id}/approve", headers=auth_headers(admin), json={})
    assert res.status_code == 200, res.text
    expense(client, auth_headers(admin), env, "10000")
    own = pending(db)[0]
    res = client.post(f"{API}/{own.id}/approve", headers=auth_headers(admin), json={})
    assert res.json()["code"] == "SELF_APPROVAL"


def test_pending_list_is_scoped_to_the_approver_role(
    client: TestClient, db: Session, admin: User, env: dict[str, int], make_user: MakeUser
) -> None:
    add_rule(db, admin, "EXPENSE", "10000", env["owner_role"])
    expense(client, auth_headers(admin), env, "15000")
    owner = auth_headers(user(db, env["owner"]))
    viewer = auth_headers(make_user(permissions=["approval.view"]))
    assert client.get(f"{API}/pending", headers=owner).json()["total"] == 1
    assert client.get(f"{API}/pending", headers=viewer).json()["total"] == 0
    admin_view = client.get(f"{API}/pending", headers=auth_headers(admin)).json()["items"]
    assert len(admin_view) == 1 and admin_view[0]["can_decide"] is False  # own request
    assert client.get(f"{API}/pending/count", headers=auth_headers(admin)).json()["count"] == 0
    history = client.get(f"{API}/history", headers=viewer, params={"status": "pending"}).json()
    assert history["total"] == 1


# --- rejection -------------------------------------------------------------------------


def test_rejection_leaves_expense_unposted_and_needs_a_remark(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    add_rule(db, admin, "EXPENSE", "10000", env["owner_role"])
    before = snapshot(db, env)
    exp = expense(client, auth_headers(admin), env, "12000")
    approval = pending(db)[0]
    owner = auth_headers(user(db, env["owner"]))
    no_reason = client.post(f"{API}/{approval.id}/reject", headers=owner, json={})
    assert no_reason.json()["code"] == "REMARK_REQUIRED"
    res = client.post(f"{API}/{approval.id}/reject", headers=owner, json={"remark": "Too much"})
    assert (res.json()["status"], res.json()["remark"]) == ("rejected", "Too much")
    voucher = client.get(f"/api/v1/money/expenses/{exp['id']}", headers=owner).json()
    assert voucher["status"] == "rejected"
    assert snapshot(db, env) == before
    approve_after = client.post(f"{API}/{approval.id}/approve", headers=owner, json={})
    assert approve_after.json()["code"] == "ALREADY_DECIDED"
    assert snapshot(db, env) == before


def test_purchase_order_pending_then_rejected_is_final(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    add_rule(db, admin, "PURCHASE_ORDER", "50000", env["owner_role"])
    h = auth_headers(admin)
    po = client.post(
        "/api/v1/purchase/orders",
        headers=h,
        json={
            "supplier_id": env["sup"],
            "warehouse_id": env["wh"],
            "items": [{"product_id": env["p1"], "qty": "100", "unit_cost": "600"}],
        },
    ).json()
    submitted = client.post(f"/api/v1/purchase/orders/{po['id']}/approve", headers=h).json()
    assert submitted["status"] == "pending_approval"
    item = submitted["items"][0]["id"]
    before = snapshot(db, env)
    receive = client.post(
        f"/api/v1/purchase/orders/{po['id']}/receive",
        headers=h,
        json={"items": [{"po_item_id": item, "qty": "1"}]},
    )
    assert receive.json()["code"] == "INVALID_STATUS"

    owner = auth_headers(user(db, env["owner"]))
    approval = pending(db)[0]
    assert (approval.document_type, approval.amount) == ("PURCHASE_ORDER", D("60000.00"))
    client.post(f"{API}/{approval.id}/reject", headers=owner, json={"remark": "Too big"})
    detail = client.get(f"/api/v1/purchase/orders/{po['id']}", headers=h).json()
    assert detail["status"] == "rejected"
    assert client.post(
        f"/api/v1/purchase/orders/{po['id']}/receive",
        headers=h,
        json={"items": [{"po_item_id": item, "qty": "1"}]},
    ).json()["code"] == ("INVALID_STATUS")
    assert client.post(f"/api/v1/purchase/orders/{po['id']}/approve", headers=h).status_code == 400
    assert client.put(f"/api/v1/purchase/orders/{po['id']}", headers=h, json={}).status_code in (
        400,
        422,
    )
    assert snapshot(db, env) == before
    cancelled = client.post(f"/api/v1/purchase/orders/{po['id']}/cancel", headers=h).json()
    assert cancelled["status"] == "cancelled"


def test_purchase_order_approval_then_receive(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    add_rule(db, admin, "PURCHASE_ORDER", "50000", env["owner_role"])
    h = auth_headers(admin)
    body = {
        "supplier_id": env["sup"],
        "warehouse_id": env["wh"],
        "items": [{"product_id": env["p1"], "qty": "100", "unit_cost": "600"}],
    }
    # a direct purchase above the threshold receives nothing until approved
    direct = client.post("/api/v1/purchase/direct", headers=h, json=body).json()
    assert direct["status"] == "pending_approval" and direct["receipts"] == []
    assert snapshot(db, env)[3:5] == (0, D("0"))
    approval = pending(db)[0]
    res = client.post(
        f"{API}/{approval.id}/approve", headers=auth_headers(user(db, env["owner"])), json={}
    )
    assert res.status_code == 200, res.text
    po = client.get(f"/api/v1/purchase/orders/{direct['id']}", headers=h).json()
    assert (po["status"], po["approved_by_name"]) == ("approved", "Business Owner")
    got = client.post(
        f"/api/v1/purchase/orders/{po['id']}/receive",
        headers=h,
        json={"items": [{"po_item_id": po["items"][0]["id"], "qty": "100"}]},
    )
    assert got.status_code == 201, got.text
    assert snapshot(db, env)[4] == D("100")

    # cancelling a pending PO closes its request
    other = client.post("/api/v1/purchase/orders", headers=h, json=body).json()
    client.post(f"/api/v1/purchase/orders/{other['id']}/approve", headers=h)
    assert len(pending(db)) == 1
    client.post(f"/api/v1/purchase/orders/{other['id']}/cancel", headers=h)
    assert pending(db) == []


def test_stock_adjustment_waits_for_approval(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    add_rule(db, admin, "STOCK_ADJUSTMENT", "1000", env["owner_role"])
    inventory.stock_in(
        db, env["p1"], env["wh"], D("10"), D("200"), PURCHASE_IN, "TEST", None, today(), admin
    )
    db.commit()
    h = auth_headers(admin)
    owner = auth_headers(user(db, env["owner"]))

    def adjust(qty: str) -> dict:
        doc = client.post(
            "/api/v1/inventory/adjustments",
            headers=h,
            json={
                "warehouse_id": env["wh"],
                "reason": "Damage",
                "items": [{"product_id": env["p1"], "direction": "decrease", "qty": qty}],
            },
        ).json()
        return client.post(f"/api/v1/inventory/adjustments/{doc['id']}/post", headers=h).json()

    small = adjust("2")  # 400 < 1000: posted straight away
    assert small["status"] == "posted"
    before = snapshot(db, env)
    big = adjust("6")  # 1,200
    assert big["status"] == "pending_approval"
    assert snapshot(db, env) == before
    approval = pending(db)[0]
    assert approval.amount == D("1200.00")
    client.post(f"{API}/{approval.id}/approve", headers=owner, json={})
    assert snapshot(db, env)[3:5] == (before[3] + 1, D("2"))
    doc = client.get(f"/api/v1/inventory/adjustments/{big['id']}", headers=h).json()
    assert doc["status"] == "posted"

    add_rule(db, admin, "STOCK_ADJUSTMENT", "100", env["owner_role"])
    rejected = adjust("1")  # 200 >= 100
    approval = pending(db)[0]
    client.post(f"{API}/{approval.id}/reject", headers=owner, json={"remark": "Recount"})
    after_reject = snapshot(db, env)
    assert after_reject[3:5] == (before[3] + 1, D("2"))
    again = client.post(f"/api/v1/inventory/adjustments/{rejected['id']}/post", headers=h)
    assert again.json()["code"] == "INVALID_STATUS"
    cancel = client.post(f"/api/v1/inventory/adjustments/{rejected['id']}/cancel", headers=h)
    assert cancel.json()["status"] == "cancelled"


def test_failed_finalize_keeps_request_pending(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    add_rule(db, admin, "EXPENSE", "10000", env["owner_role"])
    expense(client, auth_headers(admin), env, "12000")
    expense(client, auth_headers(admin), env, "9000")  # below: posted, cash now 11,000
    expense(client, auth_headers(admin), env, "5000")  # cash 6,000
    approval = pending(db)[0]
    before = snapshot(db, env)
    res = client.post(
        f"{API}/{approval.id}/approve", headers=auth_headers(user(db, env["owner"])), json={}
    )
    assert res.json()["code"] == "INSUFFICIENT_FUNDS"
    assert [a.id for a in pending(db)] == [approval.id]
    assert snapshot(db, env) == before


# --- rules -----------------------------------------------------------------------------


def test_rules_crud_and_deactivation(
    client: TestClient, db: Session, admin: User, env: dict[str, int]
) -> None:
    h = auth_headers(admin)
    store = db.scalar(select(User).where(User.username == "store"))
    assert store is not None
    body = {
        "document_type": "EXPENSE",
        "min_amount": "10000",
        "approver_role_id": env["owner_role"],
    }
    assert client.post(f"{API}/rules", headers=auth_headers(store), json=body).status_code == 403
    rule = client.post(f"{API}/rules", headers=h, json=body)
    assert rule.status_code == 201, rule.text
    rule = rule.json()
    assert (rule["document_label"], rule["approver_role_name"]) == ("Expense", "Owner")
    bad = client.post(f"{API}/rules", headers=h, json=body | {"approver_role_id": 9999})
    assert bad.json()["code"] == "INVALID_ROLE"
    updated = client.put(
        f"{API}/rules/{rule['id']}", headers=h, json=body | {"min_amount": "20000"}
    )
    assert updated.json()["min_amount"] == "20000.00"
    assert expense(client, h, env, "15000")["status"] == "posted"
    client.post(f"{API}/rules/{rule['id']}/deactivate", headers=h)
    assert expense(client, h, env, "4999")["status"] == "posted"
    listed = client.get(f"{API}/rules", headers=h).json()
    assert [r["is_active"] for r in listed["items"]] == [False]
