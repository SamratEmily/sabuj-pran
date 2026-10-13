"""Realistic demo data, created only through the service layer (the same code paths as the
API), so every ledger, balance and document number is consistent.

Run with `python -m app.seed --demo` (or `make seed-demo`). Idempotent: if the demo data is
already there (marker supplier below) it does nothing.

Story (amounts in BDT):
- Two extra warehouses/accounts, 3 suppliers and 4 customers (some with opening dues).
- PO-1 (69,400 - 1,000 discount) needs Owner approval (rule PURCHASE_ORDER >= 50,000), is
  approved and fully received; 2 rolls of film go back (purchase return).
- PO-2 (48,000) is approved directly and partially received.
- Two supplier payments; a stock transfer to the depot; a damage adjustment.
- Quotation -> sales order (confirmed + reserved); a partially delivered + invoiced order
  with a partial collection and a sales return; a fully delivered order paid in full.
- Expenses, one other income, and one expense of 15,000 waiting for Owner approval.
- 5 employees with last month's attendance.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dates import today
from app.modules.admin import service as admin_service
from app.modules.admin.schemas import CompanySettingsIn
from app.modules.approvals import service as approvals
from app.modules.approvals.models import PURCHASE_ORDER
from app.modules.auth.models import User
from app.modules.employees import service as employees
from app.modules.employees.schemas import AttendanceIn, EmployeeIn
from app.modules.inventory import service as inventory
from app.modules.inventory.schemas import AdjustmentIn, TransferIn
from app.modules.master import service as master
from app.modules.master.models import ExpenseCategory, IncomeCategory, Product, Warehouse
from app.modules.master.schemas import ProductUpdateIn, WarehouseIn
from app.modules.money import service as money
from app.modules.money.schemas import (
    AccountCreateIn,
    CollectionIn,
    ExpenseIn,
    IncomeIn,
    SupplierPaymentIn,
)
from app.modules.parties import service as parties
from app.modules.parties.models import Supplier
from app.modules.parties.schemas import PartyIn
from app.modules.purchase import service as purchase
from app.modules.purchase.schemas import PoIn, ReceiveIn
from app.modules.purchase.schemas import ReturnIn as PurchaseReturnIn
from app.modules.sales import service as sales
from app.modules.sales.schemas import DeliverIn, QuotationIn, SalesReturnIn, SoIn

MARKER_SUPPLIER = "Meghna Polymers Ltd"
D = Decimal


def _user(db: Session, username: str) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise RuntimeError(f"Demo needs the seeded user {username!r}; run the base seed first")
    return user


def _id(db: Session, model: Any, **where: Any) -> int:
    stmt = select(model.id)
    for column, value in where.items():
        stmt = stmt.where(getattr(model, column) == value)
    found = db.scalar(stmt)
    if found is None:
        raise RuntimeError(f"Demo needs {model.__name__} {where}; run the base seed first")
    return found


def _set_reorder_level(db: Session, admin: User, product_id: int, level: str) -> None:
    p = db.get(Product, product_id)
    assert p is not None
    data = ProductUpdateIn(
        code=p.code,
        name=p.name,
        category_id=p.category_id,
        unit_id=p.unit_id,
        product_type=p.product_type,
        purchase_price=p.purchase_price,
        reorder_level=D(level),
        description=p.description,
    )
    master.update_product(db, admin, product_id, data)


def _last_month_workdays(day: date) -> list[date]:
    first_this = day.replace(day=1)
    last_prev = first_this - timedelta(days=1)
    start = last_prev.replace(day=1)
    days = [start + timedelta(days=i) for i in range((last_prev - start).days + 1)]
    return [d for d in days if d.weekday() != 4]  # Friday is the weekly holiday


def seed_demo(db: Session) -> bool:
    """Create the demo data set. Returns False when it is already present."""
    if db.scalar(select(Supplier.id).where(Supplier.name == MARKER_SUPPLIER)) is not None:
        return False

    admin, owner = _user(db, "admin"), _user(db, "owner")
    store, salesman, accountant = _user(db, "store"), _user(db, "sales"), _user(db, "accounts")
    now = today()

    def ago(days: int) -> date:
        """`days` back, but never before the 1st of this month (keeps month-to-date)."""
        return max(now - timedelta(days=days), now.replace(day=1))

    # Company details for the invoice header (only if nobody filled them in yet)
    if not admin_service.get_company_settings(db).company_name:
        admin_service.update_company_settings(
            db,
            admin,
            CompanySettingsIn(
                company_name="Sabuj Plastic Industries Ltd",
                address="Plot 12, BSCIC Industrial Estate, Tongi, Gazipur",
                phone="+880 1711-000000",
                email="accounts@sabujplastic.example",
                invoice_footer_note="Thank you for your business. Goods once sold are "
                "returnable within 7 days with this invoice.",
            ),
        )

    products = {
        name: _id(db, Product, name=name)
        for name in (
            "Plastic Granules",
            "PVC Resin",
            "Packing Film",
            "Water Tank 500L",
            "PVC Pipe 1 inch",
            "Concrete Block",
        )
    }
    granules, resin, film = (
        products["Plastic Granules"],
        products["PVC Resin"],
        products["Packing Film"],
    )
    tank, pipe, block = (
        products["Water Tank 500L"],
        products["PVC Pipe 1 inch"],
        products["Concrete Block"],
    )
    main = _id(db, Warehouse, code="MAIN")
    for product_id, level in ((tank, "5"), (resin, "80"), (film, "10")):
        _set_reorder_level(db, admin, product_id, level)
    depot = master.create_warehouse(
        db, admin, WarehouseIn(name="Chattogram Depot", code="CTG", address="Agrabad, Chattogram")
    ).id

    # --- money accounts with opening balances -------------------------------------------
    dbbl = money.create_account(
        db,
        admin,
        AccountCreateIn(
            name="Dutch-Bangla Bank",
            account_type="bank",
            account_number="117-110-0045821",
            opening_balance=D("300000"),
        ),
    ).id
    petty = money.create_account(
        db,
        admin,
        AccountCreateIn(name="Petty Cash", account_type="cash", opening_balance=D("50000")),
    ).id
    rocket = money.create_account(
        db,
        admin,
        AccountCreateIn(
            name="Rocket",
            account_type="mfs",
            account_number="01711-000111",
            opening_balance=D("20000"),
        ),  # fmt: skip
    ).id

    # --- parties ------------------------------------------------------------------------
    def supplier(name: str, mobile: str, opening: str) -> int:
        out = parties.create_party(
            db,
            admin,
            parties.SUPPLIERS,
            PartyIn(name=name, mobile=mobile, address="Dhaka", opening_due=D(opening)),
        )
        return out.id

    def customer(name: str, mobile: str, address: str, opening: str) -> int:
        out = parties.create_party(
            db,
            admin,
            parties.CUSTOMERS,
            PartyIn(name=name, mobile=mobile, address=address, opening_due=D(opening)),
        )
        return out.id

    meghna = supplier(MARKER_SUPPLIER, "01811000001", "25000")
    supplier("Bengal Plastics Supply", "01811000002", "0")
    delta = supplier("Delta Packaging", "01811000003", "8000")
    rahim = customer("Rahim Traders", "01711000001", "Mirpur, Dhaka", "12000")
    karim = customer("Karim Hardware", "01711000002", "Uttara, Dhaka", "0")
    customer("Sadia Enterprise", "01711000003", "Narayanganj", "5000")
    nadia = customer("Nadia Construction", "01711000004", "Gazipur", "0")

    # --- purchasing -----------------------------------------------------------------------
    po1 = purchase.create_po(
        db,
        store,
        PoIn(
            supplier_id=meghna,
            warehouse_id=main,
            order_date=ago(6),
            discount=D("1000"),
            notes="Monthly raw material order",
            items=[
                {"product_id": granules, "qty": "200", "unit_cost": "160"},
                {"product_id": resin, "qty": "150", "unit_cost": "140"},
                {"product_id": film, "qty": "20", "unit_cost": "820"},
            ],
        ),
    )
    purchase.approve_po(db, store, po1.id)  # 68,400 >= 50,000: waits for the Owner
    request = approvals.pending_for(db, PURCHASE_ORDER, po1.id)
    if request is not None:
        approvals.approve(db, request.id, owner, "Approved: regular supplier")
    grn1 = purchase.receive_goods(
        db,
        store,
        po1.id,
        ReceiveIn(
            receipt_date=ago(5),
            items=[{"po_item_id": i.id, "qty": i.qty} for i in purchase.get_po(db, po1.id).items],
        ),
    )
    film_line = next(i for i in grn1.items if i.product_id == film)
    purchase.purchase_return(
        db,
        store,
        grn1.id,
        PurchaseReturnIn(
            return_date=ago(1),
            notes="2 rolls damaged in transit",
            items=[{"grn_item_id": film_line.id, "qty": "2"}],
        ),
    )

    po2 = purchase.create_po(
        db,
        store,
        PoIn(
            supplier_id=delta,
            warehouse_id=main,
            order_date=ago(3),
            items=[
                {"product_id": tank, "qty": "6", "unit_cost": "4200"},
                {"product_id": pipe, "qty": "300", "unit_cost": "46"},
                {"product_id": block, "qty": "300", "unit_cost": "30"},
            ],
        ),
    )
    purchase.approve_po(db, store, po2.id)  # 48,000: approved directly
    lines = {i.product_id: i.id for i in purchase.get_po(db, po2.id).items}
    purchase.receive_goods(
        db,
        store,
        po2.id,
        ReceiveIn(
            items=[
                {"po_item_id": lines[tank], "qty": "4"},  # 2 tanks still to come
                {"po_item_id": lines[pipe], "qty": "300"},
                {"po_item_id": lines[block], "qty": "300"},
            ]
        ),
    )

    money.create_voucher(
        db,
        accountant,
        money.SUPPLIER_PAYMENTS,
        SupplierPaymentIn(
            supplier_id=meghna,
            account_id=dbbl,
            amount=D("30000"),
            payment_date=ago(1),
            reference_no="CHQ-552301",
        ),  # fmt: skip
    )
    money.create_voucher(
        db,
        accountant,
        money.SUPPLIER_PAYMENTS,
        SupplierPaymentIn(supplier_id=delta, account_id=dbbl, amount=D("15000")),
    )

    # --- stock movements ------------------------------------------------------------------
    transfer = inventory.create_transfer(
        db,
        store,
        TransferIn(
            from_warehouse_id=main,
            to_warehouse_id=depot,
            note="Stock for the Chattogram depot",
            items=[{"product_id": granules, "qty": "50"}],
        ),
    )
    inventory.post_transfer(db, transfer.id, store)
    adjustment = inventory.create_adjustment(
        db,
        store,
        AdjustmentIn(
            warehouse_id=main,
            reason="Damaged in handling",
            items=[{"product_id": pipe, "direction": "decrease", "qty": "5"}],
        ),
    )
    inventory.submit_adjustment(db, adjustment.id, store)

    # --- sales ----------------------------------------------------------------------------
    # Quotation -> sales order (confirmed and reserved, nothing delivered yet)
    qt = sales.create_quotation(
        db,
        salesman,
        QuotationIn(
            customer_id=nadia,
            valid_until=now + timedelta(days=15),
            items=[
                {"product_id": block, "qty": "200", "unit_price": "45"},
                {"product_id": pipe, "qty": "100", "unit_price": "65"},
            ],
        ),
    )
    sales.set_quotation_status(db, salesman, qt.id, "send")
    sales.set_quotation_status(db, salesman, qt.id, "accept")
    so_reserved = sales.convert_to_sales_order(db, salesman, qt.id, main)
    sales.confirm_so(db, salesman, so_reserved.id)
    sales.reserve_order(db, salesman, so_reserved.id)

    # Partially delivered with invoice, partly paid, then a small return
    so_partial = sales.create_so(
        db,
        salesman,
        SoIn(
            customer_id=karim,
            warehouse_id=main,
            discount=D("300"),
            items=[
                {"product_id": tank, "qty": "3", "unit_price": "5600"},
                {"product_id": pipe, "qty": "50", "unit_price": "65"},
            ],
        ),
    )
    sales.confirm_so(db, salesman, so_partial.id)
    partial_lines = {i.product_id: i.id for i in so_partial.items}
    dlv = sales.deliver(
        db,
        salesman,
        so_partial.id,
        DeliverIn(
            items=[
                {"so_item_id": partial_lines[tank], "qty": "2"},
                {"so_item_id": partial_lines[pipe], "qty": "50"},
            ]
        ),
    )
    assert dlv.invoice_id is not None
    money.create_voucher(
        db,
        salesman,
        money.COLLECTIONS,
        CollectionIn(
            customer_id=karim,
            account_id=rocket,
            amount=D("8000"),
            invoice_id=dlv.invoice_id,
            reference_no="bKash TRX 8XK21",
        ),  # fmt: skip
    )
    invoice = sales.get_invoice(db, dlv.invoice_id)
    pipe_line = next(i for i in invoice.items if i.product_id == pipe)
    sales.sales_return(
        db,
        salesman,
        invoice.id,
        SalesReturnIn(notes="5 m cut wrong", items=[{"invoice_item_id": pipe_line.id, "qty": "5"}]),
    )

    # Fully delivered and fully paid
    so_paid = sales.create_so(
        db,
        salesman,
        SoIn(
            customer_id=rahim,
            warehouse_id=main,
            order_date=ago(2),
            items=[
                {"product_id": granules, "qty": "100", "unit_price": "185"},
                {"product_id": resin, "qty": "80", "unit_price": "160"},
            ],
        ),
    )
    sales.confirm_so(db, salesman, so_paid.id)
    dlv_paid = sales.deliver(
        db,
        salesman,
        so_paid.id,
        DeliverIn(
            delivery_date=ago(2),
            items=[{"so_item_id": i.id, "qty": i.qty_ordered} for i in so_paid.items],
        ),
    )
    paid_invoice = sales.get_invoice(db, dlv_paid.invoice_id)  # type: ignore[arg-type]
    money.create_voucher(
        db,
        accountant,
        money.COLLECTIONS,
        CollectionIn(
            customer_id=rahim,
            account_id=dbbl,
            amount=paid_invoice.total,
            invoice_id=paid_invoice.id,
            reference_no="DBBL transfer",
        ),  # fmt: skip
    )
    # A collection against the opening due (not linked to an invoice)
    money.create_voucher(
        db,
        accountant,
        money.COLLECTIONS,
        CollectionIn(customer_id=rahim, account_id=petty, amount=D("5000"), notes="Old due"),
    )

    # --- expenses and income -----------------------------------------------------------
    category = {c.name: c.id for c in db.scalars(select(ExpenseCategory))}
    for name, amount, paid_to, when in (
        ("Utilities", "4500", "DESCO", ago(4)),
        ("Transport", "1200", "Truck hire", ago(2)),
        ("Office", "850", "Stationery", now),
        ("Misc", "300", "Tea and snacks", now),
    ):
        money.create_voucher(
            db,
            accountant,
            money.EXPENSES,
            ExpenseIn(
                expense_category_id=category[name],
                account_id=petty,
                amount=D(amount),
                paid_to=paid_to,
                expense_date=when,
            ),  # fmt: skip
        )
    income_category = db.scalar(select(IncomeCategory.id).order_by(IncomeCategory.id))
    assert income_category is not None
    money.create_voucher(
        db,
        accountant,
        money.INCOMES,
        IncomeIn(
            income_category_id=income_category,
            account_id=petty,
            amount=D("2000"),
            notes="Scrap plastic sold",
        ),  # fmt: skip
    )
    # 15,000 >= the EXPENSE rule: stays pending until the Owner decides (nothing posted)
    money.create_voucher(
        db,
        accountant,
        money.EXPENSES,
        ExpenseIn(
            expense_category_id=category["Office"],
            account_id=dbbl,
            amount=D("15000"),
            paid_to="Office renovation",
        ),  # fmt: skip
    )

    # --- employees and last month's attendance -----------------------------------------
    staff = []
    for name, designation, department, salary in (
        ("Abdul Karim", "Production Supervisor", "Production", "35000"),
        ("Fatema Akter", "Accountant", "Accounts", "30000"),
        ("Rakib Hasan", "Machine Operator", "Production", "18000"),
        ("Shirin Sultana", "Sales Executive", "Sales", "22000"),
        ("Jamal Uddin", "Store Keeper", "Store", "16000"),
    ):
        emp = employees.create_employee(
            db,
            admin,
            EmployeeIn(
                full_name=name,
                designation=designation,
                department=department,
                base_salary=D(salary),
                joining_date=date(now.year - 1, 1, 15),
            ),
        )
        staff.append(emp.id)
    pattern = ("present",) * 9 + ("late",)  # roughly one late day in ten
    for n, day in enumerate(_last_month_workdays(now)):
        entries = []
        for k, emp_id in enumerate(staff):
            status = pattern[(n + k) % len(pattern)]
            if (n, k) in ((3, 2), (4, 2), (11, 4)):
                status = "absent"
            elif (n, k) in ((7, 1), (8, 1)):
                status = "leave"
            entries.append({"employee_id": emp_id, "status": status})
        employees.mark_attendance(db, admin, AttendanceIn(attendance_date=day, entries=entries))
    return True
