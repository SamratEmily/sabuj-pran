"""The only place document numbers are generated (e.g. PO-000001)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.modules.admin.models import DocumentSequence

DOC_TYPE_LABELS: dict[str, str] = {
    "QT": "Quotation",
    "SO": "Sales Order",
    "PO": "Purchase Order",
    "GRN": "Goods Receipt",
    "DLV": "Delivery",
    "INV": "Invoice",
    "SRN": "Sales Return",
    "PRN": "Purchase Return",
    "ADJ": "Stock Adjustment",
    "TRF": "Stock Transfer",
    "CNT": "Physical Count",
    "COL": "Customer Collection",
    "PAY": "Supplier Payment",
    "EXP": "Expense",
    "INC": "Other Income",
    "MTR": "Money Transfer",
    "PRL": "Payroll",
    "PRD": "Product Code",
    "CUS": "Customer Code",
    "SUP": "Supplier Code",
    "EMP": "Employee Code",
}


def format_number(prefix: str, padding: int, number: int) -> str:
    return f"{prefix}{number:0{padding}d}"


def next_document_number(db: Session, doc_type: str) -> str:
    """Reserve the next number for `doc_type` inside the caller's transaction.

    The sequence row stays locked (SELECT ... FOR UPDATE) until the caller commits or
    rolls back, so concurrent postings get unique, gap-free numbers.
    """
    seq = db.scalar(
        select(DocumentSequence).where(DocumentSequence.doc_type == doc_type).with_for_update()
    )
    if seq is None:
        raise ValueError(f"No document sequence configured for {doc_type!r}")
    number = format_number(seq.prefix, seq.padding, seq.next_number)
    seq.next_number += 1
    db.flush()
    return number


def next_free_code(db: Session, doc_type: str, column: InstrumentedAttribute[Any]) -> str:
    """Next number for a master-data code (P-0001, CUS-0001...), skipping values someone
    already typed in manually."""
    for _ in range(1000):
        code = next_document_number(db, doc_type)
        if db.scalar(select(column).where(column == code)) is None:
            return code
    raise ValueError(f"Could not find a free {doc_type} code")
