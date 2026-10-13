"""Invoice payment bookkeeping, called by the money module when a collection is linked to an
invoice (and when that collection is reversed). Runs inside the caller's transaction.

Kept apart from sales.service (which imports money for refunds) so money can import it
without an import cycle.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.sales.models import PAID, PARTIAL, UNPAID, Invoice


def lock_invoice(db: Session, invoice_id: int) -> Invoice:
    invoice = db.scalar(
        select(Invoice)
        .where(Invoice.id == invoice_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if invoice is None:
        raise AppError(404, "INVOICE_NOT_FOUND", "Invoice not found")
    return invoice


def refresh_status(invoice: Invoice) -> None:
    """paid once nothing is outstanding; partial when something was paid; else unpaid."""
    if invoice.outstanding <= 0:
        invoice.status = PAID
    elif invoice.paid_amount > 0:
        invoice.status = PARTIAL
    else:
        invoice.status = UNPAID


def apply_payment(db: Session, invoice_id: int, customer_id: int, amount: Decimal) -> Invoice:
    invoice = lock_invoice(db, invoice_id)
    if invoice.customer_id != customer_id:
        raise AppError(
            400, "INVALID_INVOICE", f"Invoice {invoice.inv_number} belongs to another customer"
        )
    outstanding = invoice.outstanding
    if amount > outstanding:
        raise AppError(
            400,
            "OVERPAYMENT",
            f"Invoice {invoice.inv_number} has only {max(outstanding, Decimal(0)):,.2f} "
            f"outstanding; cannot collect {amount:,.2f} against it",
        )
    invoice.paid_amount += amount
    refresh_status(invoice)
    db.flush()
    return invoice


def remove_payment(db: Session, invoice_id: int, amount: Decimal) -> Invoice:
    """Undo apply_payment (collection reversed)."""
    invoice = lock_invoice(db, invoice_id)
    invoice.paid_amount -= amount
    refresh_status(invoice)
    db.flush()
    return invoice
