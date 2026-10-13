from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin

COMPANY_SETTINGS_ID = 1


class CompanySetting(TimestampMixin, Base):
    """Single row (id=1) of company-wide settings."""

    __tablename__ = "company_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    company_name: Mapped[str] = mapped_column(String(150), default="")
    address: Mapped[str] = mapped_column(String(500), default="")
    phone: Mapped[str] = mapped_column(String(30), default="")
    email: Mapped[str] = mapped_column(String(150), default="")
    currency_symbol: Mapped[str] = mapped_column(String(10), default="BDT")
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Dhaka")
    invoice_footer_note: Mapped[str] = mapped_column(String(500), default="")
    logo_url: Mapped[str] = mapped_column(String(500), default="")


class DocumentSequence(TimestampMixin, Base):
    __tablename__ = "document_sequences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_type: Mapped[str] = mapped_column(String(10), unique=True)
    prefix: Mapped[str] = mapped_column(String(20))
    padding: Mapped[int] = mapped_column(Integer, default=6)
    next_number: Mapped[int] = mapped_column(Integer, default=1)
