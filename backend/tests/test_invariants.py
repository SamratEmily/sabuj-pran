"""Reconciliation invariants over the full demo data set (`python -m app.seed --demo`):
ledgers agree with stored balances, statements with views, invoices with the customer
ledger, documents with their lines, and the dashboard with the stock."""

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.permissions import PERMISSIONS
from app.demo import seed_demo
from app.modules.auth.models import User
from app.modules.dashboard import service as dashboard
from app.modules.inventory.models import StockBalance, StockTransaction
from app.modules.money import service as money
from app.modules.money.models import (
    COLLECTION,
    POSTED,
    CustomerCollection,
    MoneyAccount,
    v_cash_position,
)
from app.modules.parties import service as parties
from app.modules.parties.models import (
    CUSTOMER,
    SUPPLIER,
    Customer,
    PartyLedger,
    Supplier,
    v_customer_due,
    v_supplier_due,
)
from app.modules.purchase.models import GoodsReceiptItem, PurchaseOrderItem
from app.modules.sales.models import DeliveryItem, Invoice, SalesOrder, SalesOrderItem
from app.seed import seed_approval_rules

D = Decimal
ZERO = D("0")


@pytest.fixture
def demo(db: Session, admin: User) -> Session:
    seed_approval_rules(db)
    assert seed_demo(db) is True
    assert seed_demo(db) is False  # idempotent
    db.expire_all()
    return db


def test_demo_data_is_meaningful(demo: Session) -> None:
    s = dashboard.summary(demo, PERMISSIONS)
    for key in (
        "today_sales",
        "today_collection",
        "today_expenses",
        "today_purchase",
        "cash_balance",
        "bank_balance",
        "mfs_balance",
        "customer_due",
        "supplier_due",
        "inventory_value",
        "pending_orders_value",
    ):
        assert s[key] > 0, key
    assert s["pending_orders_count"] == 2
    assert s["estimated_profit_mtd"] != 0
    assert len(s["top_customers"]) >= 3 and len(s["top_suppliers"]) == 2
    assert {r["product_code"] for r in s["low_stock"]} >= {"P-0002", "P-0004"}
    statuses = dict(
        demo.execute(select(SalesOrder.status, func.count()).group_by(SalesOrder.status)).all()
    )
    assert statuses == {"confirmed": 1, "partially_delivered": 1, "delivered": 1}


def test_stock_ledger_matches_balances(demo: Session) -> None:
    movements = dict(
        demo.execute(
            select(
                func.concat(StockTransaction.product_id, "/", StockTransaction.warehouse_id),
                func.sum(StockTransaction.qty_in - StockTransaction.qty_out),
            ).group_by(StockTransaction.product_id, StockTransaction.warehouse_id)
        ).all()
    )
    balances = list(demo.scalars(select(StockBalance)))
    assert balances, "demo should have stock"
    for b in balances:
        key = f"{b.product_id}/{b.warehouse_id}"
        assert D(movements.get(key, 0)) == b.qty_on_hand, key
        assert b.qty_on_hand >= 0, key
        assert 0 <= b.qty_reserved <= b.qty_on_hand, key
    # every movement belongs to a balance row
    assert set(movements) == {f"{b.product_id}/{b.warehouse_id}" for b in balances}


def test_reservations_match_open_sales_order_lines(demo: Session) -> None:
    reserved: dict[tuple[int, int], Decimal] = defaultdict(lambda: ZERO)
    for so in demo.scalars(select(SalesOrder)):
        for line in so.items:
            reserved[(line.product_id, so.warehouse_id)] += line.qty_reserved
    for b in demo.scalars(select(StockBalance)):
        assert b.qty_reserved == reserved[(b.product_id, b.warehouse_id)]
    assert sum(reserved.values()) > 0


def test_money_ledger_matches_balances(demo: Session) -> None:
    view = dict(demo.execute(select(v_cash_position.c.account_id, v_cash_position.c.balance)).all())
    for account in demo.scalars(select(MoneyAccount)):
        assert money.ledger_balance(demo, account.id) == account.balance, account.name
        assert view[account.id] == account.balance, account.name
        assert account.balance >= 0, account.name


@pytest.mark.parametrize(
    ("party_type", "model", "view", "id_col"),
    [
        (CUSTOMER, Customer, v_customer_due, v_customer_due.c.customer_id),
        (SUPPLIER, Supplier, v_supplier_due, v_supplier_due.c.supplier_id),
    ],
)
def test_statement_closing_matches_view(
    demo: Session, party_type: str, model: type, view: object, id_col: object
) -> None:
    dues = dict(demo.execute(select(id_col, view.c.due)).all())  # type: ignore[attr-defined]
    parties_ = list(demo.scalars(select(model)))
    assert parties_
    for party in parties_:
        statement = parties.get_statement(demo, party_type, party.id)
        assert statement.closing_balance == dues[party.id], party.name
        assert statement.total_debit - statement.total_credit == (
            dues[party.id] if party_type == CUSTOMER else -dues[party.id]
        ), party.name
        assert parties.get_balance(demo, party_type, party.id) == dues[party.id]


def test_invoices_reconcile_with_customer_ledger(demo: Session) -> None:
    """Per customer: sum over invoices of (total - returns + refunds - paid) equals the
    ledger movement that comes from invoices - invoice debits, sales return credits, refund
    debits and collections linked to an invoice (and their reversals). Opening dues and
    advances (collections without an invoice) are excluded."""
    invoices = list(demo.scalars(select(Invoice)))
    assert invoices
    expected: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for inv in invoices:
        expected[inv.customer_id] += inv.total - inv.returned_amount + inv.refunded_amount
        expected[inv.customer_id] -= inv.paid_amount
        # paid_amount is exactly the posted collections linked to it
        linked = demo.scalar(
            select(func.coalesce(func.sum(CustomerCollection.amount), 0)).where(
                CustomerCollection.invoice_id == inv.id, CustomerCollection.status == POSTED
            )
        )
        assert D(linked) == inv.paid_amount, inv.inv_number
        # a fully settled invoice is "paid"
        assert (inv.status == "paid") == (inv.outstanding <= 0), inv.inv_number

    linked_collections = set(
        demo.scalars(
            select(CustomerCollection.id).where(CustomerCollection.invoice_id.is_not(None))
        )
    )
    from_invoices: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for row in demo.scalars(select(PartyLedger).where(PartyLedger.party_type == CUSTOMER)):
        if row.ref_type in ("INVOICE", "SALES_RETURN", "SALES_REFUND") or (
            row.ref_type in (COLLECTION, f"{COLLECTION}_REVERSAL")
            and row.ref_id in linked_collections
        ):
            from_invoices[row.party_id] += row.debit - row.credit
    assert dict(expected) == {k: v for k, v in from_invoices.items() if k in expected}
    assert set(from_invoices) <= set(expected)


def test_document_lines_reconcile(demo: Session) -> None:
    # sales order delivered qty == sum of its delivery lines; remaining never negative
    for line in demo.scalars(select(SalesOrderItem)):
        delivered = demo.scalar(
            select(func.coalesce(func.sum(DeliveryItem.qty), 0)).where(
                DeliveryItem.so_item_id == line.id
            )
        )
        assert D(delivered) == line.qty_delivered
        assert line.qty_delivered <= line.qty_ordered
    # purchase order received qty == sum of its goods receipt lines
    for line in demo.scalars(select(PurchaseOrderItem)):
        received = demo.scalar(
            select(func.coalesce(func.sum(GoodsReceiptItem.qty), 0)).where(
                GoodsReceiptItem.po_item_id == line.id
            )
        )
        assert D(received) == line.received_qty
        assert line.received_qty <= line.qty


def test_dashboard_inventory_value_is_sum_of_on_hand_times_avg_cost(demo: Session) -> None:
    exact = sum(
        (b.qty_on_hand * b.avg_cost for b in demo.scalars(select(StockBalance))), ZERO
    ).quantize(D("0.01"), ROUND_HALF_UP)
    assert dashboard.summary(demo, PERMISSIONS)["inventory_value"] == exact
    assert exact > 0
