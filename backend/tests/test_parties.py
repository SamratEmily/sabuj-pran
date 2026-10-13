from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.dates import today
from app.core.errors import AppError
from app.modules.auth.models import AuditLog, User
from app.modules.parties.models import CUSTOMER, SUPPLIER, Customer, PartyLedger, Supplier
from app.modules.parties.service import (
    CUSTOMERS,
    get_balance,
    get_statement,
    post_party_entry,
    total_due,
)
from tests.conftest import auth_headers

D = Decimal


def ledger_rows(db: Session, party_type: str, party_id: int) -> list[PartyLedger]:
    return list(
        db.scalars(
            select(PartyLedger)
            .where(PartyLedger.party_type == party_type, PartyLedger.party_id == party_id)
            .order_by(PartyLedger.id)
        )
    )


def new_party(client: TestClient, admin: User, kind: str, **fields: object) -> dict:
    res = client.post(
        f"/api/v1/{kind}", headers=auth_headers(admin), json={"name": "Party", **fields}
    )
    assert res.status_code == 201, res.text
    return res.json()


# --- opening due -----------------------------------------------------------------------


def test_opening_due_posts_one_ledger_row(client: TestClient, db: Session, admin: User) -> None:
    cust = new_party(client, admin, "customers", name="Rahim Traders", opening_due="1500.50")
    assert cust["code"] == "CUS-0001"
    assert cust["due"] == "1500.50"
    rows = ledger_rows(db, CUSTOMER, cust["id"])
    assert len(rows) == 1
    assert (rows[0].debit, rows[0].credit, rows[0].ref_type) == (D("1500.50"), D("0"), "OPENING")
    assert rows[0].entry_date == today()

    sup = new_party(client, admin, "suppliers", name="Karim Supply", opening_due="800")
    assert sup["code"] == "SUP-0001"
    rows = ledger_rows(db, SUPPLIER, sup["id"])
    assert len(rows) == 1
    assert (rows[0].debit, rows[0].credit) == (D("0"), D("800.00"))  # supplier due = credit
    assert sup["due"] == "800.00"

    none = new_party(client, admin, "customers", name="No Opening")
    assert ledger_rows(db, CUSTOMER, none["id"]) == []
    assert none["due"] == "0.00"
    assert (
        db.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.entity_type == "customer")
        )
        == 2
    )


def test_opening_due_edit_reverses_until_other_entries_exist(
    client: TestClient, db: Session, admin: User
) -> None:
    h = auth_headers(admin)
    cust = new_party(client, admin, "customers", name="Edit Me", opening_due="1000")
    payload = {"name": "Edit Me", "opening_due": "1200"}

    res = client.put(f"/api/v1/customers/{cust['id']}", headers=h, json=payload)
    assert res.status_code == 200, res.text
    assert res.json()["due"] == "1200.00"
    rows = ledger_rows(db, CUSTOMER, cust["id"])
    assert [(r.ref_type, r.debit, r.credit) for r in rows] == [
        ("OPENING", D("1000.00"), D("0.00")),
        ("OPENING_REVERSAL", D("0.00"), D("1000.00")),
        ("OPENING", D("1200.00"), D("0.00")),
    ]
    assert res.json()["has_transactions"] is False

    post_party_entry(db, CUSTOMER, cust["id"], today(), D("500"), D("0"), "INVOICE", 1, "", admin)
    locked = client.put(
        f"/api/v1/customers/{cust['id']}", headers=h, json={**payload, "opening_due": "0"}
    )
    assert locked.status_code == 400
    assert locked.json()["code"] == "OPENING_LOCKED"
    # other fields can still change
    renamed = client.put(
        f"/api/v1/customers/{cust['id']}", headers=h, json={**payload, "name": "Renamed"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["has_transactions"] is True
    assert renamed.json()["due"] == "1700.00"


# --- ledger primitives -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("debit", "credit"),
    [("10", "5"), ("0", "0"), ("-5", "0"), ("0", "-5"), ("1.005", "0")],
)
def test_entry_needs_exactly_one_positive_side(
    client: TestClient, db: Session, admin: User, debit: str, credit: str
) -> None:
    cust = new_party(client, admin, "customers")
    with pytest.raises(AppError) as err:
        post_party_entry(
            db, CUSTOMER, cust["id"], today(), D(debit), D(credit), "X", None, "", admin
        )
    assert err.value.code == "INVALID_LEDGER_ENTRY"


def test_entry_requires_existing_party(db: Session, admin: User) -> None:
    with pytest.raises(AppError) as err:
        post_party_entry(db, SUPPLIER, 999999, today(), D("1"), D("0"), "X", None, "", admin)
    assert err.value.code == "PARTY_NOT_FOUND"


def test_balance_math_customer_and_supplier(client: TestClient, db: Session, admin: User) -> None:
    cust = new_party(client, admin, "customers", opening_due="100")["id"]
    d = today()
    for debit, credit, ref in [
        ("1000", "0", "INVOICE"),
        ("0", "300", "COLLECTION"),
        ("0", "50", "SALES_RETURN"),
        ("20", "0", "REFUND"),
    ]:
        post_party_entry(db, CUSTOMER, cust, d, D(debit), D(credit), ref, None, "", admin)
    assert get_balance(db, CUSTOMER, cust) == D("770.00")  # 100 + 1000 - 300 - 50 + 20

    sup = new_party(client, admin, "suppliers", opening_due="250")["id"]
    for debit, credit, ref in [
        ("0", "2000", "GOODS_RECEIPT"),
        ("500", "0", "SUPPLIER_PAYMENT"),
        ("100", "0", "PURCHASE_RETURN"),
    ]:
        post_party_entry(db, SUPPLIER, sup, d, D(debit), D(credit), ref, None, "", admin)
    assert get_balance(db, SUPPLIER, sup) == D("1650.00")  # 250 + 2000 - 500 - 100

    # overpaid customer -> negative due (advance)
    adv = new_party(client, admin, "customers")["id"]
    post_party_entry(db, CUSTOMER, adv, d, D("0"), D("75"), "COLLECTION", None, "", admin)
    assert get_balance(db, CUSTOMER, adv) == D("-75.00")
    assert total_due(db, CUSTOMERS) == D("770.00")  # only positive dues count

    listed = client.get(
        "/api/v1/customers", headers=auth_headers(admin), params={"page_size": 100}
    ).json()
    dues = {c["id"]: c["due"] for c in listed["items"]}
    assert dues[cust] == "770.00" and dues[adv] == "-75.00"


# --- statement -------------------------------------------------------------------------


def test_statement_opening_running_and_closing(
    client: TestClient, db: Session, admin: User
) -> None:
    cust = new_party(client, admin, "customers", name="Statement Co")["id"]
    base = date(2026, 1, 1)

    def post(day: int, debit: str, credit: str, ref: str) -> None:
        post_party_entry(
            db,
            CUSTOMER,
            cust,
            base + timedelta(days=day),
            D(debit),
            D(credit),
            ref,
            None,
            ref,
            admin,
        )

    post(0, "500", "0", "INVOICE")  # before range
    post(4, "0", "200", "COLLECTION")  # before range
    post(10, "1000", "0", "INVOICE")  # in range
    post(12, "0", "300", "COLLECTION")  # in range
    post(12, "0", "100", "SALES_RETURN")  # in range, same day
    post(40, "250", "0", "INVOICE")  # after range

    st = get_statement(db, CUSTOMER, cust, base + timedelta(days=5), base + timedelta(days=20))
    assert st.opening_balance == D("300.00")
    assert [e.balance for e in st.entries] == [D("1300.00"), D("1000.00"), D("900.00")]
    assert (st.total_debit, st.total_credit) == (D("1000.00"), D("400.00"))
    assert st.closing_balance == D("900.00")
    assert st.closing_balance == st.opening_balance + st.total_debit - st.total_credit

    full = get_statement(db, CUSTOMER, cust)
    assert full.opening_balance == D("0.00")
    assert full.closing_balance == get_balance(db, CUSTOMER, cust) == D("1150.00")

    # API: query params `from`/`to`, decimals as strings
    res = client.get(
        f"/api/v1/customers/{cust}/statement",
        headers=auth_headers(admin),
        params={"from": "2026-01-06", "to": "2026-01-21"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["opening_balance"] == "300.00" and body["closing_balance"] == "900.00"
    assert [e["balance"] for e in body["entries"]] == ["1300.00", "1000.00", "900.00"]


def test_supplier_statement_uses_credit_minus_debit(
    client: TestClient, db: Session, admin: User
) -> None:
    sup = new_party(client, admin, "suppliers", opening_due="100")["id"]
    post_party_entry(db, SUPPLIER, sup, today(), D("0"), D("900"), "GOODS_RECEIPT", None, "", admin)
    post_party_entry(
        db, SUPPLIER, sup, today(), D("400"), D("0"), "SUPPLIER_PAYMENT", None, "", admin
    )
    st = get_statement(db, SUPPLIER, sup, today(), today())
    assert [e.balance for e in st.entries] == [D("100.00"), D("1000.00"), D("600.00")]
    assert st.closing_balance == D("600.00")


def test_statement_requires_permission(client: TestClient, db: Session, admin: User) -> None:
    cust = new_party(client, admin, "customers")["id"]
    sales = db.scalar(select(User).where(User.username == "sales"))
    assert sales is not None
    res = client.get(f"/api/v1/customers/{cust}/statement", headers=auth_headers(sales))
    assert res.status_code == 403  # Sales has customer.* but not party_statement.view
    assert client.get("/api/v1/customers", headers=auth_headers(sales)).status_code == 200


# --- append-only + codes ---------------------------------------------------------------


def test_ledger_rows_cannot_be_updated_or_deleted(
    client: TestClient, db: Session, admin: User
) -> None:
    cust = new_party(client, admin, "customers", opening_due="10")["id"]
    row_id = ledger_rows(db, CUSTOMER, cust)[0].id
    for sql in (
        "UPDATE party_ledger SET debit = 999 WHERE id = :id",
        "DELETE FROM party_ledger WHERE id = :id",
    ):
        with pytest.raises(OperationalError, match="append-only"), db.begin_nested():
            db.execute(text(sql), {"id": row_id})


def test_manual_and_duplicate_codes(client: TestClient, db: Session, admin: User) -> None:
    h = auth_headers(admin)
    new_party(client, admin, "customers", code="CUS-0002", name="Manual")
    auto1 = new_party(client, admin, "customers", name="Auto 1")
    auto2 = new_party(client, admin, "customers", name="Auto 2")
    assert [auto1["code"], auto2["code"]] == ["CUS-0001", "CUS-0003"]  # skips the manual code
    dup = client.post("/api/v1/customers", headers=h, json={"name": "Dup", "code": "CUS-0001"})
    assert dup.status_code == 409 and dup.json()["code"] == "CODE_TAKEN"
    assert db.scalar(select(func.count()).select_from(Customer)) == 3
    assert db.scalar(select(func.count()).select_from(Supplier)) == 0
