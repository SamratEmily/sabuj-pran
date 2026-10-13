from fastapi import APIRouter

from app.core.deps import Allow, DbDep
from app.modules.dashboard import service
from app.modules.dashboard.schemas import DashboardOut

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardOut, response_model_exclude_unset=True)
def summary(db: DbDep, user: Allow("dashboard.view")) -> DashboardOut:
    return DashboardOut(**service.summary(db, user.permission_codes))
