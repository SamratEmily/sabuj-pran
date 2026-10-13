import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal, get_db
from app.core.errors import register_error_handlers
from app.modules.admin.router import router as admin_router
from app.modules.approvals.router import router as approvals_router
from app.modules.auth.router import router as auth_router
from app.modules.auth.service import sync_permissions
from app.modules.dashboard.router import router as dashboard_router
from app.modules.employees.router import router as employees_router
from app.modules.inventory.router import router as inventory_router
from app.modules.master.router import router as master_router
from app.modules.money.router import router as money_router
from app.modules.parties.router import router as parties_router
from app.modules.purchase.router import router as purchase_router
from app.modules.sales.router import router as sales_router

logger = logging.getLogger(__name__)

api_router = APIRouter(prefix="/api/v1")


@api_router.get("/health", tags=["health"])
def health(db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok", "db": db_ok}


api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(master_router)
api_router.include_router(parties_router)
api_router.include_router(inventory_router)
api_router.include_router(purchase_router)
api_router.include_router(sales_router)
api_router.include_router(approvals_router)
api_router.include_router(employees_router)
api_router.include_router(dashboard_router)
api_router.include_router(money_router)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Keep the permissions table in step with core/permissions.py.
    try:
        with SessionLocal() as db:
            added = sync_permissions(db)
            db.commit()
        if added:
            logger.warning("Added %d new permission codes", added)
    except Exception:
        logger.exception("Permission sync failed (are migrations applied?)")
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Business Management Software", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    register_error_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
