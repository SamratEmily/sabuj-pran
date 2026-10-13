from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import InstrumentedAttribute, Session, selectinload

from app.core.audit import log_audit
from app.core.dates import today
from app.core.errors import AppError
from app.core.numbering import next_free_code
from app.core.pagination import PageParams, paginate
from app.modules.auth.models import User
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
from app.modules.master.schemas import (
    CategoryOut,
    LookupItem,
    LookupsOut,
    MoneyAccountLookup,
    NamedOut,
    PaymentMethodLookup,
    PaymentMethodOut,
    PriceIn,
    PriceOut,
    ProductCreateIn,
    ProductOut,
    ProductUpdateIn,
    UnitLookup,
    UnitOut,
    WarehouseIn,
    WarehouseLookup,
    WarehouseOut,
)
from app.modules.money.models import MoneyAccount

PRODUCT_CODE_SEQUENCE = "PRD"


# =========================================================================================
# Shared helpers for simple master tables
# =========================================================================================


@dataclass(frozen=True)
class Spec:
    """Describes a simple master table (name-like fields + is_active)."""

    model: type[Any]
    out: type[BaseModel]
    entity: str  # audit entity_type and permission resource
    label: str  # human name, e.g. "Unit"
    unique: tuple[str, ...]
    search: tuple[str, ...]
    # Column on Product referencing this table: deactivation asks for confirmation if used.
    used_by_products: InstrumentedAttribute[int] | None = None


CATEGORY = Spec(
    Category,
    CategoryOut,
    "category",
    "Category",
    ("name",),
    ("name", "description"),
    Product.category_id,
)
UNIT = Spec(
    Unit, UnitOut, "unit", "Unit", ("name", "short_code"), ("name", "short_code"), Product.unit_id
)
EXPENSE_CATEGORY = Spec(
    ExpenseCategory, NamedOut, "expense_category", "Expense category", ("name",), ("name",)
)
INCOME_CATEGORY = Spec(
    IncomeCategory, NamedOut, "income_category", "Income category", ("name",), ("name",)
)
PAYMENT_METHOD = Spec(
    PaymentMethod, PaymentMethodOut, "payment_method", "Payment method", ("name",), ("name",)
)
WAREHOUSE = Spec(
    Warehouse, WarehouseOut, "warehouse", "Warehouse", ("name", "code"), ("name", "code")
)


def _snapshot(obj: Any, fields: list[str]) -> dict[str, Any]:
    return {f: getattr(obj, f) for f in fields}


def get_item(db: Session, spec: Spec, item_id: int) -> Any:
    obj = db.get(spec.model, item_id)
    if obj is None:
        raise AppError(404, "NOT_FOUND", f"{spec.label} not found")
    return obj


def _check_unique(
    db: Session, model: Any, label: str, values: dict[str, Any], exclude_id: int | None
) -> None:
    for field, value in values.items():
        if value is None:
            continue
        stmt = select(model.id).where(getattr(model, field) == value)
        if exclude_id is not None:
            stmt = stmt.where(model.id != exclude_id)
        if db.scalar(stmt) is not None:
            nice = field.replace("_", " ")
            raise AppError(
                409, f"{field.upper()}_TAKEN", f"{label} with {nice} '{value}' already exists"
            )


def _commit(db: Session, label: str) -> None:
    """Commit; a unique-key race that slipped past the pre-check becomes a clean 409."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(409, "DUPLICATE", f"{label} already exists") from exc


def list_items(
    db: Session, spec: Spec, params: PageParams, is_active: bool | None
) -> dict[str, Any]:
    model = spec.model
    stmt = select(model).order_by(model.name, model.id)
    if params.search:
        stmt = stmt.where(
            or_(*(getattr(model, f).contains(params.search, autoescape=True) for f in spec.search))
        )
    if is_active is not None:
        stmt = stmt.where(model.is_active.is_(is_active))
    page = paginate(db, stmt, params)
    page["items"] = [spec.out.model_validate(o, from_attributes=True) for o in page["items"]]
    return page


def create_item(
    db: Session, actor: User, spec: Spec, data: BaseModel, request: Request | None = None
) -> BaseModel:
    values = data.model_dump()
    _check_unique(db, spec.model, spec.label, {f: values[f] for f in spec.unique}, None)
    obj = spec.model(**values, is_active=True)
    db.add(obj)
    db.flush()
    log_audit(
        db,
        actor,
        "create",
        spec.entity,
        obj.id,
        f"Created {spec.label.lower()} {obj.name}",
        new=values,
        request=request,
    )
    _commit(db, spec.label)
    return spec.out.model_validate(obj, from_attributes=True)


def update_item(
    db: Session,
    actor: User,
    spec: Spec,
    item_id: int,
    data: BaseModel,
    request: Request | None = None,
) -> BaseModel:
    obj = get_item(db, spec, item_id)
    values = data.model_dump()
    _check_unique(db, spec.model, spec.label, {f: values[f] for f in spec.unique}, obj.id)
    old = _snapshot(obj, list(values))
    for field, value in values.items():
        setattr(obj, field, value)
    changed = {f: v for f, v in values.items() if old[f] != v}
    if changed:
        log_audit(
            db,
            actor,
            "update",
            spec.entity,
            obj.id,
            f"Updated {spec.label.lower()} {obj.name}",
            old={f: old[f] for f in changed},
            new=changed,
            request=request,
        )
    _commit(db, spec.label)
    return spec.out.model_validate(obj, from_attributes=True)


def set_item_active(
    db: Session,
    actor: User,
    spec: Spec,
    item_id: int,
    active: bool,
    force: bool = False,
    request: Request | None = None,
) -> BaseModel:
    obj = get_item(db, spec, item_id)
    if obj.is_active != active:
        if not active and spec.used_by_products is not None and not force:
            in_use = db.scalar(
                select(func.count())
                .select_from(Product)
                .where(spec.used_by_products == obj.id, Product.is_active.is_(True))
            )
            if in_use:
                raise AppError(
                    409,
                    "CONFIRM_REQUIRED",
                    f"{in_use} active product(s) use this {spec.label.lower()}. "
                    "Deactivate it anyway? Those products keep it; it just won't be offered "
                    "for new ones.",
                )
        obj.is_active = active
        action = "activate" if active else "deactivate"
        log_audit(
            db,
            actor,
            action,
            spec.entity,
            obj.id,
            f"{action.capitalize()}d {spec.label.lower()} {obj.name}",
            old={"is_active": not active},
            new={"is_active": active},
            request=request,
        )
        db.commit()
    return spec.out.model_validate(obj, from_attributes=True)


# =========================================================================================
# Warehouses (exactly one default)
# =========================================================================================


def _make_default(db: Session, warehouse: Warehouse) -> None:
    # Lock every warehouse row so two concurrent "make default" calls serialize.
    db.execute(select(Warehouse.id).with_for_update())
    db.execute(update(Warehouse).where(Warehouse.id != warehouse.id).values(is_default=False))
    warehouse.is_default = True


def create_warehouse(
    db: Session, actor: User, data: WarehouseIn, request: Request | None = None
) -> WarehouseOut:
    values = data.model_dump()
    _check_unique(db, Warehouse, "Warehouse", {"name": data.name, "code": data.code}, None)
    first = db.scalar(select(func.count()).select_from(Warehouse)) == 0
    warehouse = Warehouse(**{**values, "is_default": False}, is_active=True)
    db.add(warehouse)
    db.flush()
    if data.is_default or first:
        _make_default(db, warehouse)
    log_audit(
        db,
        actor,
        "create",
        "warehouse",
        warehouse.id,
        f"Created warehouse {warehouse.name}",
        new={**values, "is_default": warehouse.is_default},
        request=request,
    )
    _commit(db, "Warehouse")
    return WarehouseOut.model_validate(warehouse, from_attributes=True)


def update_warehouse(
    db: Session, actor: User, warehouse_id: int, data: WarehouseIn, request: Request | None = None
) -> WarehouseOut:
    warehouse: Warehouse = get_item(db, WAREHOUSE, warehouse_id)
    _check_unique(db, Warehouse, "Warehouse", {"name": data.name, "code": data.code}, warehouse.id)
    if warehouse.is_default and not data.is_default:
        raise AppError(
            400,
            "DEFAULT_REQUIRED",
            "One warehouse must be the default. Make another warehouse the default instead.",
        )
    if data.is_default and not warehouse.is_active:
        raise AppError(400, "INACTIVE_DEFAULT", "An inactive warehouse cannot be the default")

    fields = ["name", "code", "address", "is_default"]
    old = _snapshot(warehouse, fields)
    warehouse.name, warehouse.code, warehouse.address = data.name, data.code, data.address
    if data.is_default and not warehouse.is_default:
        _make_default(db, warehouse)
    new = _snapshot(warehouse, fields)
    changed = [f for f in fields if old[f] != new[f]]
    if changed:
        log_audit(
            db,
            actor,
            "update",
            "warehouse",
            warehouse.id,
            f"Updated warehouse {warehouse.name}",
            old={f: old[f] for f in changed},
            new={f: new[f] for f in changed},
            request=request,
        )
    _commit(db, "Warehouse")
    return WarehouseOut.model_validate(warehouse, from_attributes=True)


def set_warehouse_active(
    db: Session, actor: User, warehouse_id: int, active: bool, request: Request | None = None
) -> BaseModel:
    warehouse: Warehouse = get_item(db, WAREHOUSE, warehouse_id)
    if not active and warehouse.is_default:
        raise AppError(
            400,
            "DEFAULT_WAREHOUSE",
            "The default warehouse cannot be deactivated. "
            "Make another warehouse the default first.",
        )
    return set_item_active(db, actor, WAREHOUSE, warehouse_id, active, request=request)


# =========================================================================================
# Products & prices
# =========================================================================================


def current_prices(
    db: Session, product_ids: list[int], on: date | None = None
) -> dict[int, tuple[Decimal, date]]:
    """Price in force on `on` (default today) per product: latest effective_from <= on,
    ties broken by the newest row."""
    if not product_ids:
        return {}
    on = on or today()
    ranked = (
        select(
            ProductPrice.product_id,
            ProductPrice.price,
            ProductPrice.effective_from,
            func.row_number()
            .over(
                partition_by=ProductPrice.product_id,
                order_by=(ProductPrice.effective_from.desc(), ProductPrice.id.desc()),
            )
            .label("rn"),
        )
        .where(ProductPrice.product_id.in_(product_ids), ProductPrice.effective_from <= on)
        .subquery()
    )
    rows = db.execute(
        select(ranked.c.product_id, ranked.c.price, ranked.c.effective_from).where(ranked.c.rn == 1)
    ).all()
    return {pid: (price, eff) for pid, price, eff in rows}


def current_price(db: Session, product_id: int, on: date | None = None) -> Decimal | None:
    found = current_prices(db, [product_id], on).get(product_id)
    return found[0] if found else None


def product_out(product: Product, price: tuple[Decimal, date] | None) -> ProductOut:
    return ProductOut(
        id=product.id,
        code=product.code,
        name=product.name,
        category_id=product.category_id,
        category_name=product.category.name,
        unit_id=product.unit_id,
        unit_name=product.unit.name,
        unit_code=product.unit.short_code,
        product_type=product.product_type,
        purchase_price=product.purchase_price,
        reorder_level=product.reorder_level,
        description=product.description,
        is_active=product.is_active,
        current_price=price[0] if price else None,
        price_effective_from=price[1] if price else None,
    )


def get_product(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise AppError(404, "PRODUCT_NOT_FOUND", "Product not found")
    return product


def list_products(
    db: Session,
    params: PageParams,
    category_id: int | None = None,
    product_type: str | None = None,
    is_active: bool | None = None,
) -> dict[str, Any]:
    stmt = (
        select(Product)
        .options(selectinload(Product.category), selectinload(Product.unit))
        .order_by(Product.name, Product.id)
    )
    if params.search:
        stmt = stmt.where(
            or_(
                Product.name.contains(params.search, autoescape=True),
                Product.code.contains(params.search, autoescape=True),
            )
        )
    if category_id is not None:
        stmt = stmt.where(Product.category_id == category_id)
    if product_type:
        stmt = stmt.where(Product.product_type == product_type)
    if is_active is not None:
        stmt = stmt.where(Product.is_active.is_(is_active))
    page = paginate(db, stmt, params)
    prices = current_prices(db, [p.id for p in page["items"]])
    page["items"] = [product_out(p, prices.get(p.id)) for p in page["items"]]
    return page


def _require_active_ref(
    db: Session, model: Any, ref_id: int, label: str, current: int | None
) -> None:
    obj = db.get(model, ref_id)
    if obj is None:
        raise AppError(400, f"INVALID_{label.upper()}", f"Selected {label} does not exist")
    # Keeping an existing (now inactive) reference is fine; choosing a new inactive one is not.
    if not obj.is_active and ref_id != current:
        raise AppError(400, f"INACTIVE_{label.upper()}", f"Selected {label} is inactive")


def generate_product_code(db: Session) -> str:
    return next_free_code(db, PRODUCT_CODE_SEQUENCE, Product.code)


_PRODUCT_FIELDS = [
    "code",
    "name",
    "category_id",
    "unit_id",
    "product_type",
    "purchase_price",
    "reorder_level",
    "description",
]


def create_product(
    db: Session, actor: User, data: ProductCreateIn, request: Request | None = None
) -> ProductOut:
    _require_active_ref(db, Category, data.category_id, "category", None)
    _require_active_ref(db, Unit, data.unit_id, "unit", None)
    _check_unique(db, Product, "Product", {"name": data.name, "code": data.code}, None)

    values = data.model_dump(exclude={"initial_price"})
    values["code"] = data.code or generate_product_code(db)
    product = Product(**values, is_active=True)
    db.add(product)
    db.flush()
    if data.initial_price is not None:
        db.add(
            ProductPrice(
                product_id=product.id,
                price=data.initial_price,
                effective_from=today(),
                created_by=actor.id,
            )
        )
    log_audit(
        db,
        actor,
        "create",
        "product",
        product.id,
        f"Created product {product.code} {product.name}",
        new={**values, "initial_price": data.initial_price},
        request=request,
    )
    _commit(db, "Product")
    db.refresh(product)
    return product_out(product, current_prices(db, [product.id]).get(product.id))


def update_product(
    db: Session, actor: User, product_id: int, data: ProductUpdateIn, request: Request | None = None
) -> ProductOut:
    product = get_product(db, product_id)
    _require_active_ref(db, Category, data.category_id, "category", product.category_id)
    _require_active_ref(db, Unit, data.unit_id, "unit", product.unit_id)
    values = data.model_dump()
    values["code"] = data.code or product.code  # blank keeps the current code
    _check_unique(db, Product, "Product", {"name": data.name, "code": values["code"]}, product.id)

    old = _snapshot(product, _PRODUCT_FIELDS)
    for field in _PRODUCT_FIELDS:
        setattr(product, field, values[field])
    changed = [f for f in _PRODUCT_FIELDS if old[f] != values[f]]
    if changed:
        log_audit(
            db,
            actor,
            "update",
            "product",
            product.id,
            f"Updated product {product.code}",
            old={f: old[f] for f in changed},
            new={f: values[f] for f in changed},
            request=request,
        )
    _commit(db, "Product")
    db.refresh(product)
    return product_out(product, current_prices(db, [product.id]).get(product.id))


def set_product_active(
    db: Session, actor: User, product_id: int, active: bool, request: Request | None = None
) -> ProductOut:
    product = get_product(db, product_id)
    if product.is_active != active:
        product.is_active = active
        action = "activate" if active else "deactivate"
        log_audit(
            db,
            actor,
            action,
            "product",
            product.id,
            f"{action.capitalize()}d product {product.code}",
            old={"is_active": not active},
            new={"is_active": active},
            request=request,
        )
        db.commit()
    return product_out(product, current_prices(db, [product.id]).get(product.id))


def list_product_prices(db: Session, product_id: int) -> list[PriceOut]:
    get_product(db, product_id)
    rows = db.execute(
        select(ProductPrice, User.full_name)
        .join(User, User.id == ProductPrice.created_by, isouter=True)
        .where(ProductPrice.product_id == product_id)
        .order_by(ProductPrice.effective_from.desc(), ProductPrice.id.desc())
    ).all()
    current = current_prices(db, [product_id]).get(product_id)
    current_id = None
    if current:
        # The current row is the first (newest) one in force today.
        current_id = next(p.id for p, _ in rows if p.effective_from <= today())
    return [
        PriceOut(
            id=p.id,
            product_id=p.product_id,
            price=p.price,
            effective_from=p.effective_from,
            created_by=p.created_by,
            created_by_name=name,
            created_at=p.created_at,
            is_current=p.id == current_id,
        )
        for p, name in rows
    ]


def add_price(
    db: Session, actor: User, product_id: int, data: PriceIn, request: Request | None = None
) -> PriceOut:
    """Append a new price row. Old rows are never edited."""
    product = get_product(db, product_id)
    effective = data.effective_from or today()
    row = ProductPrice(
        product_id=product.id, price=data.price, effective_from=effective, created_by=actor.id
    )
    db.add(row)
    db.flush()
    log_audit(
        db,
        actor,
        "create",
        "product_price",
        row.id,
        f"Price of {product.code} set to {data.price:.2f} from {effective.isoformat()}",
        new={"product_id": product.id, "price": data.price, "effective_from": effective},
        request=request,
    )
    db.commit()
    return next(p for p in list_product_prices(db, product.id) if p.id == row.id)


# =========================================================================================
# Lookups
# =========================================================================================


def lookups(db: Session) -> LookupsOut:
    def active(model: Any) -> list[Any]:
        return list(db.scalars(select(model).where(model.is_active.is_(True)).order_by(model.name)))

    return LookupsOut(
        categories=[LookupItem(id=c.id, name=c.name) for c in active(Category)],
        units=[UnitLookup(id=u.id, name=u.name, short_code=u.short_code) for u in active(Unit)],
        warehouses=[
            WarehouseLookup(id=w.id, name=w.name, code=w.code, is_default=w.is_default)
            for w in active(Warehouse)
        ],
        payment_methods=[
            PaymentMethodLookup(id=m.id, name=m.name, method_type=m.method_type)
            for m in active(PaymentMethod)
        ],
        expense_categories=[LookupItem(id=c.id, name=c.name) for c in active(ExpenseCategory)],
        income_categories=[LookupItem(id=c.id, name=c.name) for c in active(IncomeCategory)],
        money_accounts=[
            MoneyAccountLookup(id=a.id, name=a.name, account_type=a.account_type)
            for a in active(MoneyAccount)
        ],
    )
