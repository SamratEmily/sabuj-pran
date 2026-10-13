from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, StringConstraints

from app.core.schemas import Money, Qty, UnitCost, UtcDateTime


def _blank_to_none(v: object) -> object:
    if isinstance(v, str):
        return v.strip() or None
    return v


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Code = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9/_.-]{1,20}$")]
Text255 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)]
Text500 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
ProductCode = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9/_.-]{1,30}$")]
ProductType = Literal["raw_material", "finished_good", "trading"]
MethodType = Literal["cash", "bank", "mfs", "online"]
NonNegative = Field(ge=Decimal("0"))


# --- categories / units / expense & income categories / payment methods -----------------


class CategoryIn(BaseModel):
    name: Name
    description: Text255 = ""


class CategoryOut(CategoryIn):
    id: int
    is_active: bool


class UnitIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
    short_code: Annotated[
        str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9.]{1,10}$")
    ]


class UnitOut(UnitIn):
    id: int
    is_active: bool


class NamedIn(BaseModel):
    name: Name


class NamedOut(NamedIn):
    id: int
    is_active: bool


class PaymentMethodIn(BaseModel):
    name: Name
    method_type: MethodType


class PaymentMethodOut(PaymentMethodIn):
    id: int
    is_active: bool


# --- warehouses ------------------------------------------------------------------------


class WarehouseIn(BaseModel):
    name: Name
    code: Code
    address: Text500 = ""
    is_default: bool = False


class WarehouseOut(WarehouseIn):
    id: int
    is_active: bool


# --- products & prices -----------------------------------------------------------------


class ProductUpdateIn(BaseModel):
    # Blank code on create -> generated (P-0001 ...).
    code: Annotated[ProductCode | None, BeforeValidator(_blank_to_none)] = None
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
    category_id: int
    unit_id: int
    product_type: ProductType
    purchase_price: Annotated[UnitCost, NonNegative] = Decimal("0")
    reorder_level: Annotated[Qty, NonNegative] = Decimal("0")
    description: Text500 = ""


class ProductCreateIn(ProductUpdateIn):
    # Optional first selling price, effective today.
    initial_price: Annotated[Money, NonNegative] | None = None


class ProductOut(BaseModel):
    id: int
    code: str
    name: str
    category_id: int
    category_name: str
    unit_id: int
    unit_name: str
    unit_code: str
    product_type: ProductType
    purchase_price: UnitCost
    reorder_level: Qty
    description: str
    is_active: bool
    current_price: Money | None
    price_effective_from: date | None


class PriceIn(BaseModel):
    price: Annotated[Money, NonNegative]
    # Defaults to today (Asia/Dhaka). May be in the past or future.
    effective_from: date | None = None


class PriceOut(BaseModel):
    id: int
    product_id: int
    price: Money
    effective_from: date
    created_by: int
    created_by_name: str | None
    created_at: UtcDateTime
    is_current: bool


# --- lookups ---------------------------------------------------------------------------


class LookupItem(BaseModel):
    id: int
    name: str


class UnitLookup(LookupItem):
    short_code: str


class WarehouseLookup(LookupItem):
    code: str
    is_default: bool


class PaymentMethodLookup(LookupItem):
    method_type: MethodType


class MoneyAccountLookup(LookupItem):
    account_type: Literal["cash", "bank", "mfs"]


class LookupsOut(BaseModel):
    categories: list[LookupItem]
    units: list[UnitLookup]
    warehouses: list[WarehouseLookup]
    payment_methods: list[PaymentMethodLookup]
    expense_categories: list[LookupItem]
    income_categories: list[LookupItem]
    money_accounts: list[MoneyAccountLookup]
