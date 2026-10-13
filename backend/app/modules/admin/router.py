from datetime import date

from fastapi import APIRouter, Request, Response

from app.core.deps import Allow, DbDep
from app.core.pagination import Page, PageParamsDep
from app.modules.admin import service
from app.modules.admin.schemas import (
    AuditFacetsOut,
    AuditLogOut,
    CompanySettingsIn,
    CompanySettingsOut,
    DocumentSequenceIn,
    DocumentSequenceOut,
    PermissionGroupOut,
    RoleIn,
    RoleOut,
    RolePermissionsIn,
    RolePermissionsOut,
    UserAdminOut,
    UserCreateIn,
    UserPasswordResetIn,
    UserUpdateIn,
)

router = APIRouter(prefix="/admin", tags=["admin"])


# --- users -----------------------------------------------------------------------------


@router.get("/users")
def list_users(
    db: DbDep,
    params: PageParamsDep,
    _: Allow("user.view"),
    role_id: int | None = None,
    is_active: bool | None = None,
) -> Page[UserAdminOut]:
    return Page[UserAdminOut](**service.list_users(db, params, role_id, is_active))


@router.post("/users", status_code=201)
def create_user(
    data: UserCreateIn, db: DbDep, actor: Allow("user.create"), request: Request
) -> UserAdminOut:
    return service.create_user(db, actor, data, request)


@router.get("/users/{user_id}")
def get_user(user_id: int, db: DbDep, _: Allow("user.view")) -> UserAdminOut:
    return service.user_admin_out(service.get_user(db, user_id))


@router.put("/users/{user_id}")
def update_user(
    user_id: int, data: UserUpdateIn, db: DbDep, actor: Allow("user.edit"), request: Request
) -> UserAdminOut:
    return service.update_user(db, actor, user_id, data, request)


@router.post("/users/{user_id}/deactivate")
def deactivate_user(
    user_id: int, db: DbDep, actor: Allow("user.delete"), request: Request
) -> UserAdminOut:
    return service.set_user_active(db, actor, user_id, False, request)


@router.post("/users/{user_id}/activate")
def activate_user(
    user_id: int, db: DbDep, actor: Allow("user.delete"), request: Request
) -> UserAdminOut:
    return service.set_user_active(db, actor, user_id, True, request)


@router.post("/users/{user_id}/reset-password")
def reset_user_password(
    user_id: int,
    data: UserPasswordResetIn,
    db: DbDep,
    actor: Allow("user.edit"),
    request: Request,
) -> UserAdminOut:
    return service.reset_user_password(db, actor, user_id, data.password, request)


# --- roles & permissions ---------------------------------------------------------------


@router.get("/roles")
def list_roles(db: DbDep, params: PageParamsDep, _: Allow("role.view")) -> Page[RoleOut]:
    return Page[RoleOut](**service.list_roles(db, params))


@router.post("/roles", status_code=201)
def create_role(data: RoleIn, db: DbDep, actor: Allow("role.create"), request: Request) -> RoleOut:
    return service.create_role(db, actor, data, request)


@router.put("/roles/{role_id}")
def update_role(
    role_id: int, data: RoleIn, db: DbDep, actor: Allow("role.edit"), request: Request
) -> RoleOut:
    return service.update_role(db, actor, role_id, data, request)


@router.delete("/roles/{role_id}", status_code=204)
def delete_role(role_id: int, db: DbDep, actor: Allow("role.delete"), request: Request) -> Response:
    service.delete_role(db, actor, role_id, request)
    return Response(status_code=204)


@router.get("/permissions")
def list_permissions(db: DbDep, _: Allow("role.view")) -> list[PermissionGroupOut]:
    return service.permission_groups(db)


@router.get("/roles/{role_id}/permissions")
def get_role_permissions(role_id: int, db: DbDep, _: Allow("role.view")) -> RolePermissionsOut:
    return service.get_role_permissions(db, role_id)


@router.put("/roles/{role_id}/permissions")
def set_role_permissions(
    role_id: int,
    data: RolePermissionsIn,
    db: DbDep,
    actor: Allow("role.edit"),
    request: Request,
) -> RolePermissionsOut:
    return service.set_role_permissions(db, actor, role_id, data.codes, request)


# --- audit log -------------------------------------------------------------------------


@router.get("/audit-logs")
def list_audit_logs(
    db: DbDep,
    params: PageParamsDep,
    _: Allow("audit_log.view"),
    date_from: date | None = None,
    date_to: date | None = None,
    user_id: int | None = None,
    entity_type: str | None = None,
    action: str | None = None,
    entity_id: str | None = None,
) -> Page[AuditLogOut]:
    return Page[AuditLogOut](
        **service.list_audit_logs(
            db, params, date_from, date_to, user_id, entity_type, action, entity_id
        )
    )


@router.get("/audit-logs/facets")
def audit_facets(db: DbDep, _: Allow("audit_log.view")) -> AuditFacetsOut:
    return service.audit_facets(db)


# --- company settings ------------------------------------------------------------------


@router.get("/company-settings")
def get_company_settings(db: DbDep, _: Allow("company_setting.view")) -> CompanySettingsOut:
    return CompanySettingsOut.model_validate(service.get_company_settings(db), from_attributes=True)


@router.put("/company-settings")
def update_company_settings(
    data: CompanySettingsIn, db: DbDep, actor: Allow("company_setting.edit"), request: Request
) -> CompanySettingsOut:
    row = service.update_company_settings(db, actor, data, request)
    return CompanySettingsOut.model_validate(row, from_attributes=True)


# --- document sequences ----------------------------------------------------------------


@router.get("/document-sequences")
def list_sequences(
    db: DbDep, params: PageParamsDep, _: Allow("document_sequence.view")
) -> Page[DocumentSequenceOut]:
    return Page[DocumentSequenceOut](**service.list_sequences(db, params))


@router.put("/document-sequences/{seq_id}")
def update_sequence(
    seq_id: int,
    data: DocumentSequenceIn,
    db: DbDep,
    actor: Allow("document_sequence.edit"),
    request: Request,
) -> DocumentSequenceOut:
    return service.update_sequence(db, actor, seq_id, data, request)
