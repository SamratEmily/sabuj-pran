from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import Field, PlainSerializer


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


# DATETIME columns hold naive UTC; serialize with "Z" so clients don't read them as local time.
UtcDateTime = Annotated[datetime, PlainSerializer(_utc_iso, return_type=str)]


def _fixed(places: int) -> PlainSerializer:
    # JSON only: model_dump() in Python keeps Decimal so services never compute on strings.
    return PlainSerializer(lambda v: f"{v:.{places}f}", return_type=str, when_used="json")


# Decimal API types: validated to the column's precision, always returned as strings with a
# fixed number of places ("12.50"), never floats. Match DECIMAL(18,2|3|4) in the database.
Money = Annotated[Decimal, Field(max_digits=18, decimal_places=2), _fixed(2)]
Qty = Annotated[Decimal, Field(max_digits=18, decimal_places=3), _fixed(3)]
UnitCost = Annotated[Decimal, Field(max_digits=18, decimal_places=4), _fixed(4)]
