from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core.deps import Allow, CurrentUser, DbDep
from app.core.pagination import Page, PageParamsDep
from app.modules.master import service
from app.modules.master.schemas import (
    CategoryIn,
    CategoryOut,
    LookupsOut,
    NamedIn,
    NamedOut,
    PaymentMethodIn,
    PaymentMethodOut,
    PriceIn,
    PriceOut,
    ProductCreateIn,
    ProductOut,
    ProductType,
    ProductUpdateIn,
    UnitIn,
    UnitOut,
    WarehouseIn,
    WarehouseOut,
)
from app.modules.master.service import Spec

router = APIRouter(prefix="/master", tags=["master"])


def _simple_crud(
    path: str, spec: Spec, schema_in: type[BaseModel], schema_out: type[BaseModel]
) -> None:
    """Standard list/create/update/deactivate/activate routes for a simple master table.
    Permissions: `<spec.entity>.view|create|edit|delete` (deactivate/activate use delete)."""
    perm = spec.entity

    @router.get(path, name=f"list_{perm}")
    def list_(
        db: DbDep, params: PageParamsDep, _: Allow(f"{perm}.view"), is_active: bool | None = None
    ) -> Page[schema_out]:
        return Page[schema_out](**service.list_items(db, spec, params, is_active))

    @router.post(path, status_code=201, name=f"create_{perm}")
    def create(
        data: schema_in, db: DbDep, actor: Allow(f"{perm}.create"), request: Request
    ) -> schema_out:
        return service.create_item(db, actor, spec, data, request)

    @router.put(f"{path}/{{item_id}}", name=f"update_{perm}")
    def update_(
        item_id: int, data: schema_in, db: DbDep, actor: Allow(f"{perm}.edit"), request: Request
    ) -> schema_out:
        return service.update_item(db, actor, spec, item_id, data, request)

    @router.post(f"{path}/{{item_id}}/deactivate", name=f"deactivate_{perm}")
    def deactivate(
        item_id: int,
        db: DbDep,
        actor: Allow(f"{perm}.delete"),
        request: Request,
        force: bool = False,
    ) -> schema_out:
        return service.set_item_active(db, actor, spec, item_id, False, force, request)

    @router.post(f"{path}/{{item_id}}/activate", name=f"activate_{perm}")
    def activate(
        item_id: int, db: DbDep, actor: Allow(f"{perm}.delete"), request: Request
    ) -> schema_out:
        return service.set_item_active(db, actor, spec, item_id, True, request=request)


_simple_crud("/categories", service.CATEGORY, CategoryIn, CategoryOut)
_simple_crud("/units", service.UNIT, UnitIn, UnitOut)
_simple_crud("/expense-categories", service.EXPENSE_CATEGORY, NamedIn, NamedOut)
_simple_crud("/income-categories", service.INCOME_CATEGORY, NamedIn, NamedOut)
_simple_crud("/payment-methods", service.PAYMENT_METHOD, PaymentMethodIn, PaymentMethodOut)


# --- warehouses ------------------------------------------------------------------------


@router.get("/warehouses")
def list_warehouses(
    db: DbDep, params: PageParamsDep, _: Allow("warehouse.view"), is_active: bool | None = None
) -> Page[WarehouseOut]:
    return Page[WarehouseOut](**service.list_items(db, service.WAREHOUSE, params, is_active))


@router.post("/warehouses", status_code=201)
def create_warehouse(
    data: WarehouseIn, db: DbDep, actor: Allow("warehouse.create"), request: Request
) -> WarehouseOut:
    return service.create_warehouse(db, actor, data, request)


@router.put("/warehouses/{warehouse_id}")
def update_warehouse(
    warehouse_id: int,
    data: WarehouseIn,
    db: DbDep,
    actor: Allow("warehouse.edit"),
    request: Request,
) -> WarehouseOut:
    return service.update_warehouse(db, actor, warehouse_id, data, request)


@router.post("/warehouses/{warehouse_id}/deactivate")
def deactivate_warehouse(
    warehouse_id: int, db: DbDep, actor: Allow("warehouse.delete"), request: Request
) -> WarehouseOut:
    return service.set_warehouse_active(db, actor, warehouse_id, False, request)


@router.post("/warehouses/{warehouse_id}/activate")
def activate_warehouse(
    warehouse_id: int, db: DbDep, actor: Allow("warehouse.delete"), request: Request
) -> WarehouseOut:
    return service.set_warehouse_active(db, actor, warehouse_id, True, request)


# --- products --------------------------------------------------------------------------


@router.get("/products")
def list_products(
    db: DbDep,
    params: PageParamsDep,
    _: Allow("product.view"),
    category_id: int | None = None,
    product_type: ProductType | None = None,
    is_active: bool | None = None,
) -> Page[ProductOut]:
    return Page[ProductOut](
        **service.list_products(db, params, category_id, product_type, is_active)
    )


@router.post("/products", status_code=201)
def create_product(
    data: ProductCreateIn, db: DbDep, actor: Allow("product.create"), request: Request
) -> ProductOut:
    return service.create_product(db, actor, data, request)


@router.get("/products/{product_id}")
def get_product(product_id: int, db: DbDep, _: Allow("product.view")) -> ProductOut:
    product = service.get_product(db, product_id)
    return service.product_out(product, service.current_prices(db, [product.id]).get(product.id))


@router.put("/products/{product_id}")
def update_product(
    product_id: int,
    data: ProductUpdateIn,
    db: DbDep,
    actor: Allow("product.edit"),
    request: Request,
) -> ProductOut:
    return service.update_product(db, actor, product_id, data, request)


@router.post("/products/{product_id}/deactivate")
def deactivate_product(
    product_id: int, db: DbDep, actor: Allow("product.delete"), request: Request
) -> ProductOut:
    return service.set_product_active(db, actor, product_id, False, request)


@router.post("/products/{product_id}/activate")
def activate_product(
    product_id: int, db: DbDep, actor: Allow("product.delete"), request: Request
) -> ProductOut:
    return service.set_product_active(db, actor, product_id, True, request)


# --- prices ----------------------------------------------------------------------------


@router.get("/prices")
def price_list(
    db: DbDep,
    params: PageParamsDep,
    _: Allow("price.view"),
    category_id: int | None = None,
    product_type: ProductType | None = None,
) -> Page[ProductOut]:
    """Active products with their current selling price."""
    return Page[ProductOut](**service.list_products(db, params, category_id, product_type, True))


@router.get("/products/{product_id}/prices")
def list_product_prices(product_id: int, db: DbDep, _: Allow("price.view")) -> list[PriceOut]:
    return service.list_product_prices(db, product_id)


@router.post("/products/{product_id}/prices", status_code=201)
def add_price(
    product_id: int, data: PriceIn, db: DbDep, actor: Allow("price.create"), request: Request
) -> PriceOut:
    return service.add_price(db, actor, product_id, data, request)


# --- lookups ---------------------------------------------------------------------------


@router.get("/lookups")
def lookups(db: DbDep, _: CurrentUser) -> LookupsOut:
    """Active reference data for dropdowns. Any logged-in user (names only, no prices)."""
    return service.lookups(db)
