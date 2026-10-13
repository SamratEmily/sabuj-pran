"""Employees: records, attendance sheet, payroll math, one run per month, paying through
the money engine exactly once, frozen paid runs."""

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.dates import today
from app.modules.auth.models import User
from app.modules.employees.service import absence_deduction
from app.modules.money import service as money
from app.modules.money.models import MoneyAccount, MoneyTransaction
from tests.conftest import auth_headers

API = "/api/v1/employees"
D = Decimal
MONTH = "2025-01"


@pytest.fixture
def h(admin: User) -> dict[str, str]:
    return auth_headers(admin)


@pytest.fixture
def cash(db: Session) -> int:
    account = db.scalar(select(MoneyAccount.id).where(MoneyAccount.name == "Cash in Hand"))
    assert account is not None
    return account


def add_employee(client: TestClient, h: dict, name: str, salary: str, **extra: object) -> dict:
    res = client.post(API, headers=h, json={"full_name": name, "base_salary": salary, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def mark(client: TestClient, h: dict, day: str, entries: dict[int, str]) -> dict:
    res = client.put(
        f"{API}/attendance",
        headers=h,
        json={
            "attendance_date": day,
            "entries": [{"employee_id": k, "status": v} for k, v in entries.items()],
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def fund(db: Session, admin: User, account_id: int, amount: str) -> None:
    money.money_in(db, account_id, D(amount), "INCOME", "TEST", None, today(), admin)
    db.commit()


def balance(db: Session, account_id: int) -> Decimal:
    db.expire_all()
    account = db.get(MoneyAccount, account_id)
    assert account is not None
    return account.balance


def payroll_rows(db: Session) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(MoneyTransaction)
            .where(MoneyTransaction.txn_type == "PAYROLL")
        )
        or 0
    )


@pytest.fixture
def staff(client: TestClient, h: dict) -> dict[str, dict]:
    """Three employees with January attendance: Rahim 2 absent + 1 leave + 1 late,
    Karim 3 absent, Salma none; one inactive employee."""
    rahim = add_employee(client, h, "Rahim Uddin", "30000", designation="Operator")
    karim = add_employee(client, h, "Karim Mia", "10001", department="Store")
    salma = add_employee(client, h, "Salma Begum", "25000")
    gone = add_employee(client, h, "Old Staff", "9000")
    for day, statuses in {
        "2025-01-05": {rahim["id"]: "absent", karim["id"]: "absent", salma["id"]: "present"},
        "2025-01-06": {rahim["id"]: "absent", karim["id"]: "absent", salma["id"]: "late"},
        "2025-01-07": {rahim["id"]: "leave", karim["id"]: "absent", salma["id"]: "leave"},
        "2025-01-08": {rahim["id"]: "late", karim["id"]: "present"},
        "2025-02-01": {rahim["id"]: "absent"},  # other month: ignored
    }.items():
        mark(client, h, day, statuses)
    client.post(f"{API}/{gone['id']}/deactivate", headers=h)
    return {"rahim": rahim, "karim": karim, "salma": salma, "gone": gone}


# --- employees & attendance ------------------------------------------------------------


def test_employee_codes_user_link_and_permissions(
    client: TestClient, db: Session, admin: User, h: dict
) -> None:
    first = add_employee(client, h, "Rahim Uddin", "30000", mobile="01711000000")
    assert (first["code"], first["base_salary"], first["mobile"]) == (
        "EMP-0001",
        "30000.00",
        "01711000000",
    )
    linked = add_employee(client, h, "Karim Mia", "1000", user_id=admin.id)
    assert linked["username"] == "admin"
    dup = client.post(API, headers=h, json={"full_name": "X", "user_id": admin.id})
    assert dup.json()["code"] == "USER_TAKEN"
    taken = client.post(API, headers=h, json={"full_name": "X", "code": "EMP-0001"})
    assert taken.json()["code"] == "CODE_TAKEN"
    edited = client.put(
        f"{API}/{first['id']}",
        headers=h,
        json={"full_name": "Rahim Uddin", "base_salary": "32000", "designation": "Supervisor"},
    ).json()
    assert (edited["code"], edited["base_salary"], edited["designation"]) == (
        "EMP-0001",
        "32000.00",
        "Supervisor",
    )
    sales = db.scalar(select(User).where(User.username == "sales"))
    assert sales is not None
    assert client.get(API, headers=auth_headers(sales)).status_code == 403
    listed = client.get(API, headers=h, params={"search": "karim"}).json()
    assert [e["full_name"] for e in listed["items"]] == ["Karim Mia"]


def test_attendance_sheet_prefills_present_and_rows_are_editable(
    client: TestClient, h: dict
) -> None:
    a = add_employee(client, h, "A", "1000")
    b = add_employee(client, h, "B", "1000")
    sheet = client.get(f"{API}/attendance", headers=h, params={"attendance_date": "2025-03-01"})
    rows = sheet.json()["rows"]
    assert [(r["status"], r["saved"]) for r in rows] == [("present", False), ("present", False)]

    saved = mark(client, h, "2025-03-01", {a["id"]: "present", b["id"]: "absent"})
    assert [(r["status"], r["saved"]) for r in saved["rows"]] == [
        ("present", True),
        ("absent", True),
    ]
    assert saved["summary"] == {"present": 1, "absent": 1, "leave": 0, "late": 0}
    one = mark(client, h, "2025-03-01", {b["id"]: "leave"})  # edit a single row
    assert [r["status"] for r in one["rows"]] == ["present", "leave"]

    future = (today() + timedelta(days=1)).isoformat()
    res = client.put(
        f"{API}/attendance",
        headers=h,
        json={
            "attendance_date": future,
            "entries": [{"employee_id": a["id"], "status": "present"}],
        },
    )
    assert res.json()["code"] == "FUTURE_DATE"


# --- payroll ---------------------------------------------------------------------------


def test_deduction_math(client: TestClient, h: dict, staff: dict[str, dict]) -> None:
    assert absence_deduction(D("30000"), 2) == D("2000.00")
    assert absence_deduction(D("10001"), 3) == D("1000.10")
    assert absence_deduction(D("100"), 31) == D("100")  # never more than the salary

    res = client.post(f"{API}/payroll", headers=h, json={"month": MONTH})
    assert res.status_code == 201, res.text
    run = res.json()
    lines = {i["employee_name"]: i for i in run["items"]}
    assert set(lines) == {"Rahim Uddin", "Karim Mia", "Salma Begum"}  # inactive left out
    rahim, karim, salma = lines["Rahim Uddin"], lines["Karim Mia"], lines["Salma Begum"]
    # only "absent" deducts; leave / late / other months don't
    assert (rahim["absent_days"], rahim["absence_deduction"], rahim["net_pay"]) == (
        2,
        "2000.00",
        "28000.00",
    )
    assert (karim["absent_days"], karim["absence_deduction"], karim["net_pay"]) == (
        3,
        "1000.10",
        "9000.90",
    )
    assert (salma["absent_days"], salma["net_pay"]) == (0, "25000.00")
    assert (run["prl_number"], run["status"], run["total_net"]) == (
        "PRL-000001",
        "draft",
        "62000.90",
    )

    # bonus and other deduction while draft: net = base - deductions + bonus
    edited = client.put(
        f"{API}/payroll/{run['id']}",
        headers=h,
        json={"items": [{"id": rahim["id"], "bonus": "1500", "other_deduction": "250.50"}]},
    ).json()
    line = next(i for i in edited["items"] if i["id"] == rahim["id"])
    assert line["net_pay"] == "29249.50"  # 30000 - 2000 - 250.50 + 1500
    assert edited["total_net"] == "63250.40"
    negative = client.put(
        f"{API}/payroll/{run['id']}",
        headers=h,
        json={"items": [{"id": karim["id"], "other_deduction": "9000.91"}]},
    )
    assert negative.json()["code"] == "NEGATIVE_NET_PAY"


def test_one_run_per_month(client: TestClient, h: dict, staff: dict[str, dict]) -> None:
    first = client.post(f"{API}/payroll", headers=h, json={"month": MONTH}).json()
    again = client.post(f"{API}/payroll", headers=h, json={"month": MONTH})
    assert (again.status_code, again.json()["code"]) == (409, "PAYROLL_EXISTS")
    other_month = client.post(f"{API}/payroll", headers=h, json={"month": "2025-02"})
    assert other_month.status_code == 201
    bad = client.post(f"{API}/payroll", headers=h, json={"month": "2025-13"})
    assert bad.status_code == 422

    # a cancelled run frees the month
    assert client.post(f"{API}/payroll/{first['id']}/cancel", headers=h).json()["status"] == (
        "cancelled"
    )
    regenerated = client.post(f"{API}/payroll", headers=h, json={"month": MONTH})
    assert regenerated.status_code == 201
    assert regenerated.json()["prl_number"] == "PRL-000003"


def test_pay_posts_money_once_and_freezes_the_run(
    client: TestClient,
    db: Session,
    admin: User,
    h: dict,
    cash: int,
    staff: dict[str, dict],
) -> None:
    run = client.post(f"{API}/payroll", headers=h, json={"month": MONTH}).json()
    fund(db, admin, cash, "50000")

    # not enough money: nothing happens
    short = client.post(f"{API}/payroll/{run['id']}/pay", headers=h, json={"account_id": cash})
    assert short.json()["code"] == "INSUFFICIENT_FUNDS"
    assert (balance(db, cash), payroll_rows(db)) == (D("50000.00"), 0)
    assert client.get(f"{API}/payroll/{run['id']}", headers=h).json()["status"] == "draft"

    fund(db, admin, cash, "20000")
    res = client.post(
        f"{API}/payroll/{run['id']}/pay",
        headers=h,
        json={"account_id": cash, "payment_date": "2025-02-01"},
    )
    assert res.status_code == 200, res.text
    paid = res.json()
    assert (paid["status"], paid["account_name"], paid["payment_date"]) == (
        "paid",
        "Cash in Hand",
        "2025-02-01",
    )
    assert balance(db, cash) == D("70000.00") - D("62000.90")
    row = db.scalar(select(MoneyTransaction).where(MoneyTransaction.txn_type == "PAYROLL"))
    assert row is not None
    assert (row.direction, row.amount, row.ref_type, row.ref_id) == (
        "out",
        D("62000.90"),
        "PAYROLL",
        run["id"],
    )
    assert money.ledger_balance(db, cash) == balance(db, cash)

    again = client.post(f"{API}/payroll/{run['id']}/pay", headers=h, json={"account_id": cash})
    assert again.json()["code"] == "ALREADY_PAID"
    assert payroll_rows(db) == 1

    # paid runs can't change
    item = paid["items"][0]["id"]
    edit = client.put(
        f"{API}/payroll/{run['id']}", headers=h, json={"items": [{"id": item, "bonus": "1"}]}
    )
    assert edit.json()["code"] == "INVALID_STATUS"
    assert client.post(f"{API}/payroll/{run['id']}/cancel", headers=h).json()["code"] == (
        "INVALID_STATUS"
    )
    assert client.post(f"{API}/payroll", headers=h, json={"month": MONTH}).status_code == 409
    assert client.get(f"{API}/payroll/{run['id']}", headers=h).json()["total_net"] == "62000.90"


def test_payroll_permissions(
    client: TestClient, db: Session, h: dict, staff: dict[str, dict]
) -> None:
    accounts = db.scalar(select(User).where(User.username == "accounts"))
    store = db.scalar(select(User).where(User.username == "store"))
    assert accounts and store
    ha = auth_headers(accounts)
    assert client.post(f"{API}/payroll", headers=ha, json={"month": MONTH}).status_code == 201
    assert client.get(f"{API}/attendance", headers=ha).status_code == 200
    assert client.put(
        f"{API}/attendance",
        headers=ha,
        json={
            "attendance_date": "2025-03-01",
            "entries": [{"employee_id": staff["salma"]["id"], "status": "present"}],
        },
    ).status_code == (403)
    assert client.get(f"{API}/payroll", headers=auth_headers(store)).status_code == 403
