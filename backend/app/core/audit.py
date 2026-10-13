from decimal import Decimal
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.modules.auth.models import AuditLog, User


def _json(values: dict[str, Any] | None) -> dict[str, Any] | None:
    # Decimals are stored as strings, never floats.
    return None if values is None else jsonable_encoder(values, custom_encoder={Decimal: str})


def client_ip(request: Request | None) -> str | None:
    return request.client.host if request is not None and request.client else None


def log_audit(
    db: Session,
    user: User | None,
    action: str,
    entity_type: str,
    entity_id: int | str | None,
    summary: str,
    old: dict[str, Any] | None = None,
    new: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditLog:
    """Add an audit row to the caller's transaction (does not commit)."""
    entry = AuditLog(
        user_id=user.id if user is not None else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        summary=summary[:500],
        old_values=_json(old),
        new_values=_json(new),
        ip_address=client_ip(request),
    )
    db.add(entry)
    return entry
