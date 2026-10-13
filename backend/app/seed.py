"""Idempotent seed: permissions, system roles, demo users, master reference data and demo
products. Run with `python -m app.seed`.

Re-running only adds what is missing; it never removes permissions or resets passwords.
"""

import argparse
from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dates import today
from app.core.db import SessionLocal
from app.core.permissions import CRUD_ACTIONS, PERMISSIONS
from app.core.security import hash_password
from app.modules.approvals.models import ApprovalRule
from app.modules.auth.models import Permission, Role, User
from app.modules.auth.service import ADMIN_ROLE, sync_permissions
from app.modules.master.models import (
    Category,
    ExpenseCategory,
    IncomeCategory,
    PaymentMethod,
    Product,
    ProductPrice,
    Unit,
    Warehouse,
)
from app.modules.master.service import generate_product_code
from app.modules.money.models import MoneyAccount

DEMO_PASSWORD = "Admin@123"


def _crud(*resources: str) -> list[str]:
    return [f"{r}.{a}" for r in resources for a in CRUD_ACTIONS]


ROLE_PERMISSIONS: dict[str, tuple[str, list[str]]] = {
    ADMIN_ROLE: ("Full access", PERMISSIONS),
    "Owner": (
        "View everything and approve",
        [p for p in PERMISSIONS if p.endswith(".view")]
        + ["approval.approve", "dashboard.view", "audit_log.view"],
    ),
    "Sales": (
        "Customers, sales documents and collections",
        _crud("customer", "quotation", "sales_order", "delivery", "invoice", "sales_return")
        + _crud("collection")
        + ["reservation.manage", "stock.view", "product.view", "dashboard.view"],
    ),
    "Purchase/Store": (
        "Suppliers, purchasing and stock",
        _crud("supplier", "purchase_order", "goods_receipt", "purchase_return")
        + [p for p in PERMISSIONS if p.startswith("stock")]
        + ["product.view", "supplier_payment.view", "dashboard.view"],
    ),
    "Accounts": (
        "Money in and out",
        _crud(
            "collection",
            "supplier_payment",
            "expense",
            "income",
            "money_transfer",
            "money_account",
            "payment_method",
            "expense_category",
            "income_category",
        )
        + ["customer.view", "supplier.view", "party_statement.view", "dashboard.view"]
        + ["invoice.view"]  # collect against invoices
        + _crud("payroll")
        + ["employee.view", "attendance.view"],
    ),
}

# username, full name, role
DEMO_USERS: list[tuple[str, str, str]] = [
    ("admin", "System Admin", ADMIN_ROLE),
    ("owner", "Business Owner", "Owner"),
    ("sales", "Sales User", "Sales"),
    ("store", "Store User", "Purchase/Store"),
    ("accounts", "Accounts User", "Accounts"),
]


UNITS = [
    ("Kilogram", "KG"),
    ("Piece", "PCS"),
    ("Roll", "ROLL"),
    ("Block", "BLK"),
    ("Meter", "M"),
    ("Packet", "PKT"),
]
CATEGORIES = [
    ("Raw Materials", "Inputs used in production"),
    ("Finished Goods", "Products made for sale"),
]
EXPENSE_CATEGORIES = ["Rent", "Utilities", "Salary", "Transport", "Office", "Misc"]
INCOME_CATEGORIES = ["Other Income"]
PAYMENT_METHODS = [
    ("Cash", "cash"),
    ("Bank Transfer", "bank"),
    ("bKash", "mfs"),
    ("Nagad", "mfs"),
    ("Online", "online"),
]
# name, category, unit code, type, purchase price (cost), selling price
DEMO_PRODUCTS = [
    ("Plastic Granules", "Raw Materials", "KG", "raw_material", "165.0000", "185.00"),
    ("PVC Resin", "Raw Materials", "KG", "raw_material", "142.5000", "160.00"),
    ("Packing Film", "Raw Materials", "ROLL", "raw_material", "850.0000", "950.00"),
    ("Water Tank 500L", "Finished Goods", "PCS", "finished_good", "4200.0000", "5600.00"),
    ("PVC Pipe 1 inch", "Finished Goods", "M", "finished_good", "48.0000", "65.00"),
    ("Concrete Block", "Finished Goods", "BLK", "finished_good", "32.0000", "45.00"),
]


def _ensure(db: Session, model: type, name: str, **fields: object) -> object:
    obj = db.scalar(select(model).where(model.name == name))  # type: ignore[attr-defined]
    if obj is None:
        obj = model(name=name, is_active=True, **fields)
        db.add(obj)
        db.flush()
    return obj


# name, type, payment method
MONEY_ACCOUNTS = [
    ("Cash in Hand", "cash", "Cash"),
    ("City Bank", "bank", "Bank Transfer"),
    ("bKash", "mfs", "bKash"),
    ("Nagad", "mfs", "Nagad"),
]


def seed_money(db: Session) -> None:
    methods = {m.name: m.id for m in db.scalars(select(PaymentMethod))}
    for name, account_type, method in MONEY_ACCOUNTS:
        if db.scalar(select(MoneyAccount.id).where(MoneyAccount.name == name)) is None:
            db.add(
                MoneyAccount(
                    name=name,
                    account_type=account_type,
                    payment_method_id=methods.get(method),
                    is_active=True,
                )
            )
    db.flush()


def seed_master(db: Session, admin: User) -> None:
    units = {code: _ensure(db, Unit, name, short_code=code) for name, code in UNITS}
    categories = {n: _ensure(db, Category, n, description=d) for n, d in CATEGORIES}
    for name in EXPENSE_CATEGORIES:
        _ensure(db, ExpenseCategory, name)
    for name in INCOME_CATEGORIES:
        _ensure(db, IncomeCategory, name)
    for name, method_type in PAYMENT_METHODS:
        _ensure(db, PaymentMethod, name, method_type=method_type)
    has_default = db.scalar(select(Warehouse.id).where(Warehouse.is_default.is_(True)))
    _ensure(db, Warehouse, "Main Warehouse", code="MAIN", is_default=has_default is None)

    for name, category, unit, ptype, cost, price in DEMO_PRODUCTS:
        if db.scalar(select(Product.id).where(Product.name == name)) is not None:
            continue
        product = Product(
            code=generate_product_code(db),
            name=name,
            category_id=categories[category].id,  # type: ignore[attr-defined]
            unit_id=units[unit].id,  # type: ignore[attr-defined]
            product_type=ptype,
            purchase_price=Decimal(cost),
            reorder_level=Decimal("0"),
            is_active=True,
        )
        db.add(product)
        db.flush()
        db.add(
            ProductPrice(
                product_id=product.id,
                price=Decimal(price),
                effective_from=today(),
                created_by=admin.id,
            )
        )
    db.flush()


def _ensure_role(db: Session, name: str, description: str, codes: Iterable[str]) -> Role:
    role = db.scalar(select(Role).where(Role.name == name))
    if role is None:
        role = Role(name=name, description=description, is_system=True)
        db.add(role)
    wanted = set(codes)
    have = {p.code for p in role.permissions}
    missing = wanted - have
    if missing:
        role.permissions.extend(db.scalars(select(Permission).where(Permission.code.in_(missing))))
    return role


def seed(db: Session) -> None:
    sync_permissions(db)
    roles = {
        name: _ensure_role(db, name, description, codes)
        for name, (description, codes) in ROLE_PERMISSIONS.items()
    }
    db.flush()
    for username, full_name, role_name in DEMO_USERS:
        if db.scalar(select(User.id).where(User.username == username)) is None:
            db.add(
                User(
                    username=username,
                    full_name=full_name,
                    email=f"{username}@example.com",
                    password_hash=hash_password(DEMO_PASSWORD),
                    role_id=roles[role_name].id,
                    is_active=True,
                    must_change_password=False,
                )
            )
    db.flush()
    admin = db.scalar(select(User).where(User.username == "admin"))
    assert admin is not None
    seed_master(db, admin)
    seed_money(db)
    db.commit()


# document type, minimum amount, approver role
DEMO_APPROVAL_RULES = [("EXPENSE", "10000", "Owner"), ("PURCHASE_ORDER", "50000", "Owner")]


def seed_approval_rules(db: Session) -> None:
    """Demo rules, added once per document type (kept out of `seed` so tests start
    without rules and create the ones they need)."""
    for document_type, amount, role_name in DEMO_APPROVAL_RULES:
        if db.scalar(select(ApprovalRule.id).where(ApprovalRule.document_type == document_type)):
            continue
        role = db.scalar(select(Role).where(Role.name == role_name))
        assert role is not None
        db.add(
            ApprovalRule(
                document_type=document_type,
                min_amount=Decimal(amount),
                approver_role_id=role.id,
                is_active=True,
            )
        )
    db.commit()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Seed roles, users and master data.")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="also create the demo business data (suppliers, orders, sales, money...)",
    )
    args = parser.parse_args(argv)
    with SessionLocal() as db:
        seed(db)
        seed_approval_rules(db)
        if args.demo:
            from app.demo import seed_demo  # imports every module's services

            created = seed_demo(db)
            print("Demo data created." if created else "Demo data already present; skipped.")
    print("Seed complete.")


if __name__ == "__main__":
    main()
