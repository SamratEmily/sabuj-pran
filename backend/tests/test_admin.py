import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, insert, select
from sqlalchemy.orm import Session

from app.core.dates import today
from app.core.db import make_engine
from app.core.numbering import DOC_TYPE_LABELS, next_document_number
from app.core.permissions import PERMISSIONS
from app.modules.admin.models import DocumentSequence
from app.modules.auth.models import AuditLog, Role, User
from tests.conftest import TEST_PASSWORD, MakeUser, auth_headers

API = "/api/v1/admin"


def audit_rows(db: Session, entity_type: str, action: str) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog).where(AuditLog.entity_type == entity_type, AuditLog.action == action)
        )
    )


def role_id(db: Session, name: str) -> int:
    rid = db.scalar(select(Role.id).where(Role.name == name))
    assert rid is not None
    return rid


# --- users -----------------------------------------------------------------------------


def test_create_user_and_audit(client: TestClient, db: Session, admin: User) -> None:
    res = client.post(
        f"{API}/users",
        headers=auth_headers(admin),
        json={
            "full_name": "New Clerk",
            "username": "clerk",
            "email": "clerk@example.com",
            "role_id": role_id(db, "Sales"),
            "password": "Temp1234!",
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["role_name"] == "Sales"
    assert body["must_change_password"] is True
    assert body["created_at"].endswith("Z")
    assert "password" not in str(audit_rows(db, "user", "create")[0].new_values)

    login = client.post("/api/v1/auth/login", json={"identifier": "clerk", "password": "Temp1234!"})
    assert login.status_code == 200

    dup = client.post(
        f"{API}/users",
        headers=auth_headers(admin),
        json={
            "full_name": "Again",
            "username": "clerk",
            "role_id": role_id(db, "Sales"),
            "password": "Temp1234!",
        },
    )
    assert dup.status_code == 409
    assert dup.json()["code"] == "USERNAME_TAKEN"


def test_list_users_filters(client: TestClient, db: Session, admin: User) -> None:
    headers = auth_headers(admin)
    all_users = client.get(f"{API}/users", headers=headers).json()
    assert all_users["total"] == 5

    sales = client.get(f"{API}/users", headers=headers, params={"role_id": role_id(db, "Sales")})
    assert [u["username"] for u in sales.json()["items"]] == ["sales"]

    found = client.get(f"{API}/users", headers=headers, params={"search": "accou"})
    assert [u["username"] for u in found.json()["items"]] == ["accounts"]

    client.post(f"{API}/users/{_id(db, 'store')}/deactivate", headers=headers)
    inactive = client.get(f"{API}/users", headers=headers, params={"is_active": False})
    assert [u["username"] for u in inactive.json()["items"]] == ["store"]


def _id(db: Session, username: str) -> int:
    uid = db.scalar(select(User.id).where(User.username == username))
    assert uid is not None
    return uid


def test_cannot_deactivate_self(client: TestClient, db: Session, admin: User) -> None:
    res = client.post(f"{API}/users/{admin.id}/deactivate", headers=auth_headers(admin))
    assert res.status_code == 400
    assert res.json()["code"] == "CANNOT_DEACTIVATE_SELF"


def test_last_admin_protection(
    client: TestClient, db: Session, admin: User, make_user: MakeUser
) -> None:
    # A non-Admin-role operator with full user permissions tries to remove the only Admin.
    operator = make_user("operator", ["user.view", "user.edit", "user.delete"])
    headers = auth_headers(operator)

    res = client.post(f"{API}/users/{admin.id}/deactivate", headers=headers)
    assert res.status_code == 400
    assert res.json()["code"] == "LAST_ADMIN"

    demote = client.put(
        f"{API}/users/{admin.id}",
        headers=headers,
        json={"full_name": admin.full_name, "role_id": role_id(db, "Sales")},
    )
    assert demote.status_code == 400
    assert demote.json()["code"] == "LAST_ADMIN"

    # With a second active Admin, deactivating the first is allowed.
    second = client.post(
        f"{API}/users",
        headers=auth_headers(admin),
        json={
            "full_name": "Second Admin",
            "username": "admin2",
            "role_id": role_id(db, "Admin"),
            "password": "Temp1234!",
        },
    )
    assert second.status_code == 201
    ok = client.post(f"{API}/users/{admin.id}/deactivate", headers=headers)
    assert ok.status_code == 200
    assert ok.json()["is_active"] is False
    assert audit_rows(db, "user", "deactivate")


def test_admin_resets_user_password(client: TestClient, db: Session, admin: User) -> None:
    sales_id = _id(db, "sales")
    res = client.post(
        f"{API}/users/{sales_id}/reset-password",
        headers=auth_headers(admin),
        json={"password": "TempPass9!"},
    )
    assert res.status_code == 200
    assert res.json()["must_change_password"] is True
    login = client.post(
        "/api/v1/auth/login", json={"identifier": "sales", "password": "TempPass9!"}
    )
    assert login.status_code == 200
    assert login.json()["user"]["must_change_password"] is True
    assert audit_rows(db, "user", "reset_password")


def test_user_endpoints_require_permission(client: TestClient, make_user: MakeUser) -> None:
    user = make_user("viewer", ["user.view"])
    headers = auth_headers(user)
    assert client.get(f"{API}/users", headers=headers).status_code == 200
    res = client.post(
        f"{API}/users",
        headers=headers,
        json={"full_name": "X", "username": "xyz", "role_id": 1, "password": TEST_PASSWORD},
    )
    assert res.status_code == 403


# --- roles & permissions ---------------------------------------------------------------


def test_role_permission_replacement_applies_on_next_request(
    client: TestClient, db: Session, admin: User, make_user: MakeUser
) -> None:
    user = make_user("auditor", ["audit_log.view"])
    headers = auth_headers(user)
    assert client.get(f"{API}/audit-logs", headers=headers).status_code == 200

    res = client.put(
        f"{API}/roles/{user.role_id}/permissions",
        headers=auth_headers(admin),
        json={"codes": ["user.view"]},
    )
    assert res.status_code == 200, res.text
    db.expire_all()  # same session as the app in tests; production gets a fresh session

    assert client.get(f"{API}/audit-logs", headers=headers).status_code == 403
    assert client.get(f"{API}/users", headers=headers).status_code == 200
    audit = audit_rows(db, "role", "update")[-1]
    assert audit.new_values == {"added": ["user.view"]}
    assert audit.old_values == {"removed": ["audit_log.view"]}


def test_admin_role_cannot_lose_permissions(client: TestClient, db: Session, admin: User) -> None:
    res = client.put(
        f"{API}/roles/{admin.role_id}/permissions",
        headers=auth_headers(admin),
        json={"codes": PERMISSIONS[:-1]},
    )
    assert res.status_code == 400
    assert res.json()["code"] == "ADMIN_PERMISSIONS_LOCKED"


def test_unknown_permission_rejected(client: TestClient, db: Session, admin: User) -> None:
    res = client.put(
        f"{API}/roles/{role_id(db, 'Sales')}/permissions",
        headers=auth_headers(admin),
        json={"codes": ["product.view", "product.fly"]},
    )
    assert res.status_code == 400
    assert res.json()["code"] == "UNKNOWN_PERMISSION"


def test_role_crud_rules(client: TestClient, db: Session, admin: User) -> None:
    headers = auth_headers(admin)
    created = client.post(f"{API}/roles", headers=headers, json={"name": "Cashier"})
    assert created.status_code == 201
    rid = created.json()["id"]

    renamed = client.put(
        f"{API}/roles/{rid}", headers=headers, json={"name": "Head Cashier", "description": "x"}
    )
    assert renamed.json()["name"] == "Head Cashier"

    assert (
        client.put(f"{API}/roles/{admin.role_id}", headers=headers, json={"name": "Boss"}).json()[
            "code"
        ]
        == "SYSTEM_ROLE"
    )
    assert client.delete(f"{API}/roles/{admin.role_id}", headers=headers).json()["code"] == (
        "SYSTEM_ROLE"
    )

    # in use -> blocked
    client.post(
        f"{API}/users",
        headers=headers,
        json={"full_name": "C", "username": "cashier1", "role_id": rid, "password": "Temp1234!"},
    )
    in_use = client.delete(f"{API}/roles/{rid}", headers=headers)
    assert in_use.status_code == 400
    assert in_use.json()["code"] == "ROLE_IN_USE"

    empty = client.post(f"{API}/roles", headers=headers, json={"name": "Temp"}).json()["id"]
    assert client.delete(f"{API}/roles/{empty}", headers=headers).status_code == 204
    assert db.get(Role, empty) is None
    assert audit_rows(db, "role", "delete")


def test_permission_groups(client: TestClient, admin: User) -> None:
    groups = client.get(f"{API}/permissions", headers=auth_headers(admin)).json()
    assert sum(len(g["permissions"]) for g in groups) == len(PERMISSIONS)
    sales = next(g for g in groups if g["module"] == "sales")
    assert {
        "code": "reservation.manage",
        "description": "Reserve and release stock for sales orders",
    } in sales["permissions"]


# --- audit log -------------------------------------------------------------------------


def test_audit_log_filters_newest_first(client: TestClient, db: Session, admin: User) -> None:
    headers = auth_headers(admin)
    client.post(f"{API}/roles", headers=headers, json={"name": "R1"})
    client.post(f"{API}/roles", headers=headers, json={"name": "R2"})

    res = client.get(f"{API}/audit-logs", headers=headers, params={"entity_type": "role"})
    items = res.json()["items"]
    assert [i["summary"] for i in items[:2]] == ["Created role R2", "Created role R1"]
    assert items[0]["user_name"] == admin.full_name

    by_user = client.get(f"{API}/audit-logs", headers=headers, params={"user_id": admin.id})
    assert by_user.json()["total"] >= 2

    d = today()
    in_range = client.get(
        f"{API}/audit-logs",
        headers=headers,
        params={"date_from": str(d), "date_to": str(d), "action": "create"},
    )
    assert in_range.json()["total"] >= 2
    past = client.get(
        f"{API}/audit-logs",
        headers=headers,
        params={"date_to": str(d - timedelta(days=1))},
    )
    assert past.json()["total"] == 0

    facets = client.get(f"{API}/audit-logs/facets", headers=headers).json()
    assert "role" in facets["entity_types"] and "create" in facets["actions"]


# --- company settings ------------------------------------------------------------------


def test_company_settings(client: TestClient, db: Session, admin: User) -> None:
    headers = auth_headers(admin)
    current = client.get(f"{API}/company-settings", headers=headers).json()
    assert current["currency_symbol"] == "BDT" and current["timezone"] == "Asia/Dhaka"

    res = client.put(
        f"{API}/company-settings",
        headers=headers,
        json={**current, "company_name": "Sabuj Pran Ltd", "phone": "01700000000"},
    )
    assert res.status_code == 200
    assert res.json()["company_name"] == "Sabuj Pran Ltd"
    audit = audit_rows(db, "company_setting", "update")[-1]
    assert audit.new_values == {"company_name": "Sabuj Pran Ltd", "phone": "01700000000"}

    bad = client.put(
        f"{API}/company-settings", headers=headers, json={**current, "timezone": "Mars/Base"}
    )
    assert bad.status_code == 400
    assert bad.json()["code"] == "INVALID_TIMEZONE"


# --- document numbering ----------------------------------------------------------------


def test_numbering_sequential(db: Session) -> None:
    assert next_document_number(db, "PO") == "PO-000001"
    assert next_document_number(db, "PO") == "PO-000002"
    with pytest.raises(ValueError):
        next_document_number(db, "NOPE")


def test_sequence_update_only_upward(client: TestClient, db: Session, admin: User) -> None:
    headers = auth_headers(admin)
    seqs = client.get(f"{API}/document-sequences", headers=headers).json()
    assert seqs["total"] == len(DOC_TYPE_LABELS)
    inv = next(s for s in seqs["items"] if s["doc_type"] == "INV")
    assert inv["preview"] == "INV-000001" and inv["label"] == "Invoice"

    ok = client.put(
        f"{API}/document-sequences/{inv['id']}",
        headers=headers,
        json={"prefix": "INV/26/", "padding": 4, "next_number": 100},
    )
    assert ok.status_code == 200
    assert ok.json()["preview"] == "INV/26/0100"
    assert next_document_number(db, "INV") == "INV/26/0100"

    down = client.put(
        f"{API}/document-sequences/{inv['id']}",
        headers=headers,
        json={"prefix": "INV/26/", "padding": 4, "next_number": 5},
    )
    assert down.status_code == 400
    assert down.json()["code"] == "SEQUENCE_DECREASE"
    assert audit_rows(db, "document_sequence", "update")


def test_numbering_unique_under_concurrency(engine: Engine) -> None:
    """20 threads, each in its own connection/transaction, all asking at once."""
    threads_count = 20
    eng = make_engine(engine.url.render_as_string(hide_password=False), pool_size=threads_count)
    with eng.begin() as conn:
        conn.execute(delete(DocumentSequence).where(DocumentSequence.doc_type == "TST"))
        conn.execute(
            insert(DocumentSequence).values(doc_type="TST", prefix="TST-", padding=6, next_number=1)
        )

    barrier = threading.Barrier(threads_count)
    results: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            with Session(eng) as session:
                barrier.wait()
                number = next_document_number(session, "TST")
                session.commit()
            with lock:
                results.append(number)
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assert below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(threads_count)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert not errors, errors
        assert len(results) == threads_count
        assert len(set(results)) == threads_count  # no duplicates
        assert sorted(results) == [f"TST-{n:06d}" for n in range(1, threads_count + 1)]
        with Session(eng) as session:
            assert (
                session.scalar(
                    select(DocumentSequence.next_number).where(DocumentSequence.doc_type == "TST")
                )
                == threads_count + 1
            )
            assert session.scalar(select(func.count()).select_from(DocumentSequence)) == (
                len(DOC_TYPE_LABELS) + 1
            )
    finally:
        with eng.begin() as conn:
            conn.execute(delete(DocumentSequence).where(DocumentSequence.doc_type == "TST"))
        eng.dispose()
