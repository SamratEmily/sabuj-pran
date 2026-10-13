from collections.abc import Sequence
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.audit import log_audit
from app.core.dates import local_day_end_utc, local_day_start_utc
from app.core.errors import AppError
from app.core.numbering import DOC_TYPE_LABELS, format_number
from app.core.pagination import PageParams, paginate
from app.core.security import hash_password
from app.modules.admin.models import COMPANY_SETTINGS_ID, CompanySetting, DocumentSequence
from app.modules.admin.schemas import (
    AuditFacetsOut,
    AuditLogOut,
    CompanySettingsIn,
    DocumentSequenceIn,
    DocumentSequenceOut,
    PermissionGroupOut,
    PermissionOut,
    RoleIn,
    RoleOut,
    RolePermissionsOut,
    UserAdminOut,
    UserCreateIn,
    UserUpdateIn,
)
from app.modules.auth.models import AuditLog, Permission, Role, User
from app.modules.auth.service import ADMIN_ROLE

# =========================================================================================
# Users
# =========================================================================================


def user_admin_out(user: User) -> UserAdminOut:
    return UserAdminOut(
        id=user.id,
        full_name=user.full_name,
        username=user.username,
        email=user.email,
        mobile=user.mobile,
        role_id=user.role_id,
        role_name=user.role.name,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


def _user_snapshot(user: User) -> dict[str, Any]:
    return {
        "full_name": user.full_name,
        "username": user.username,
        "email": user.email,
        "mobile": user.mobile,
        "role_id": user.role_id,
        "is_active": user.is_active,
    }


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise AppError(404, "USER_NOT_FOUND", "User not found")
    return user


def _get_role_for_user(db: Session, role_id: int) -> Role:
    role = db.get(Role, role_id)
    if role is None:
        raise AppError(400, "INVALID_ROLE", "Selected role does not exist")
    return role


def _check_user_unique(db: Session, values: dict[str, str | None], exclude_id: int | None) -> None:
    for field, value in values.items():
        if value is None:
            continue
        stmt = select(User.id).where(getattr(User, field) == value)
        if exclude_id is not None:
            stmt = stmt.where(User.id != exclude_id)
        if db.scalar(stmt) is not None:
            raise AppError(409, f"{field.upper()}_TAKEN", f"{field.capitalize()} is already in use")


def _ensure_not_last_admin(db: Session, user: User, action: str) -> None:
    """Block `action` if `user` is the only active Admin. Locks the Admin role row so two
    concurrent requests cannot each remove a different "other" admin."""
    if not user.is_active or user.role.name != ADMIN_ROLE:
        return
    admin_role = db.scalar(select(Role).where(Role.name == ADMIN_ROLE).with_for_update())
    assert admin_role is not None
    others = db.scalar(
        select(func.count())
        .select_from(User)
        .where(User.role_id == admin_role.id, User.is_active.is_(True), User.id != user.id)
    )
    if not others:
        raise AppError(
            400, "LAST_ADMIN", f"Cannot {action}: at least one active Admin user is required"
        )


def list_users(
    db: Session, params: PageParams, role_id: int | None, is_active: bool | None
) -> dict[str, Any]:
    stmt = select(User).options(selectinload(User.role)).order_by(User.full_name, User.id)
    if params.search:
        stmt = stmt.where(
            or_(
                *(
                    col.contains(params.search, autoescape=True)
                    for col in (User.full_name, User.username, User.email, User.mobile)
                )
            )
        )
    if role_id is not None:
        stmt = stmt.where(User.role_id == role_id)
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    page = paginate(db, stmt, params)
    page["items"] = [user_admin_out(u) for u in page["items"]]
    return page


def create_user(
    db: Session, actor: User, data: UserCreateIn, request: Request | None = None
) -> UserAdminOut:
    role = _get_role_for_user(db, data.role_id)
    _check_user_unique(
        db, {"username": data.username, "email": data.email, "mobile": data.mobile}, None
    )
    user = User(
        full_name=data.full_name,
        username=data.username,
        email=data.email,
        mobile=data.mobile,
        role=role,
        password_hash=hash_password(data.password),
        is_active=True,
        must_change_password=data.must_change_password,
    )
    db.add(user)
    db.flush()
    log_audit(
        db,
        actor,
        "create",
        "user",
        user.id,
        f"Created user {user.username} ({role.name})",
        new=_user_snapshot(user),
        request=request,
    )
    db.commit()
    db.refresh(user)
    return user_admin_out(user)


def update_user(
    db: Session, actor: User, user_id: int, data: UserUpdateIn, request: Request | None = None
) -> UserAdminOut:
    user = get_user(db, user_id)
    role = _get_role_for_user(db, data.role_id)
    if role.id != user.role_id:
        _ensure_not_last_admin(db, user, "change the role of the last Admin")
    _check_user_unique(db, {"email": data.email, "mobile": data.mobile}, user.id)

    old = _user_snapshot(user)
    user.full_name = data.full_name
    user.email = data.email
    user.mobile = data.mobile
    user.role = role
    db.flush()
    log_audit(
        db,
        actor,
        "update",
        "user",
        user.id,
        f"Updated user {user.username}",
        old=old,
        new=_user_snapshot(user),
        request=request,
    )
    db.commit()
    return user_admin_out(user)


def set_user_active(
    db: Session, actor: User, user_id: int, active: bool, request: Request | None = None
) -> UserAdminOut:
    user = get_user(db, user_id)
    if user.is_active == active:
        return user_admin_out(user)
    if not active:
        if user.id == actor.id:
            raise AppError(400, "CANNOT_DEACTIVATE_SELF", "You cannot deactivate your own account")
        _ensure_not_last_admin(db, user, "deactivate the last Admin")
    user.is_active = active
    action = "activate" if active else "deactivate"
    log_audit(
        db,
        actor,
        action,
        "user",
        user.id,
        f"{action.capitalize()}d user {user.username}",
        old={"is_active": not active},
        new={"is_active": active},
        request=request,
    )
    db.commit()
    return user_admin_out(user)


def reset_user_password(
    db: Session, actor: User, user_id: int, password: str, request: Request | None = None
) -> UserAdminOut:
    user = get_user(db, user_id)
    user.password_hash = hash_password(password)
    user.must_change_password = True
    log_audit(
        db,
        actor,
        "reset_password",
        "user",
        user.id,
        f"Set a temporary password for {user.username}",
        request=request,
    )
    db.commit()
    return user_admin_out(user)


# =========================================================================================
# Roles & permissions
# =========================================================================================


def get_role(db: Session, role_id: int, lock: bool = False) -> Role:
    stmt = select(Role).where(Role.id == role_id)
    if lock:
        stmt = stmt.with_for_update()
    role = db.scalar(stmt)
    if role is None:
        raise AppError(404, "ROLE_NOT_FOUND", "Role not found")
    return role


def _role_outs(db: Session, roles: Sequence[Role]) -> list[RoleOut]:
    ids = [r.id for r in roles]
    user_counts = dict(
        db.execute(
            select(User.role_id, func.count()).where(User.role_id.in_(ids)).group_by(User.role_id)
        ).all()
    )
    return [
        RoleOut(
            id=r.id,
            name=r.name,
            description=r.description,
            is_system=r.is_system,
            user_count=user_counts.get(r.id, 0),
            permission_count=len(r.permissions),
        )
        for r in roles
    ]


def list_roles(db: Session, params: PageParams) -> dict[str, Any]:
    stmt = select(Role).options(selectinload(Role.permissions)).order_by(Role.id)
    if params.search:
        stmt = stmt.where(Role.name.contains(params.search, autoescape=True))
    page = paginate(db, stmt, params)
    page["items"] = _role_outs(db, page["items"])
    return page


def _check_role_name(db: Session, name: str, exclude_id: int | None) -> None:
    stmt = select(Role.id).where(Role.name == name)
    if exclude_id is not None:
        stmt = stmt.where(Role.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise AppError(409, "ROLE_NAME_TAKEN", "A role with this name already exists")


def create_role(db: Session, actor: User, data: RoleIn, request: Request | None = None) -> RoleOut:
    _check_role_name(db, data.name, None)
    role = Role(name=data.name, description=data.description, is_system=False)
    db.add(role)
    db.flush()
    log_audit(
        db,
        actor,
        "create",
        "role",
        role.id,
        f"Created role {role.name}",
        new=data.model_dump(),
        request=request,
    )
    db.commit()
    return _role_outs(db, [role])[0]


def update_role(
    db: Session, actor: User, role_id: int, data: RoleIn, request: Request | None = None
) -> RoleOut:
    role = get_role(db, role_id)
    if role.is_system and data.name != role.name:
        raise AppError(400, "SYSTEM_ROLE", "System roles cannot be renamed")
    _check_role_name(db, data.name, role.id)
    old = {"name": role.name, "description": role.description}
    role.name = data.name
    role.description = data.description
    log_audit(
        db,
        actor,
        "update",
        "role",
        role.id,
        f"Updated role {role.name}",
        old=old,
        new=data.model_dump(),
        request=request,
    )
    db.commit()
    return _role_outs(db, [role])[0]


def delete_role(db: Session, actor: User, role_id: int, request: Request | None = None) -> None:
    role = get_role(db, role_id, lock=True)
    if role.is_system:
        raise AppError(400, "SYSTEM_ROLE", "System roles cannot be deleted")
    if db.scalar(select(func.count()).select_from(User).where(User.role_id == role.id)):
        raise AppError(400, "ROLE_IN_USE", "This role is assigned to users and cannot be deleted")
    old = {
        "name": role.name,
        "description": role.description,
        "permissions": sorted(p.code for p in role.permissions),
    }
    db.delete(role)
    log_audit(
        db,
        actor,
        "delete",
        "role",
        role_id,
        f"Deleted role {old['name']}",
        old=old,
        request=request,
    )
    db.commit()


def permission_groups(db: Session) -> list[PermissionGroupOut]:
    groups: dict[str, list[PermissionOut]] = {}
    for p in db.scalars(select(Permission).order_by(Permission.id)):
        groups.setdefault(p.module, []).append(
            PermissionOut(code=p.code, description=p.description)
        )
    return [PermissionGroupOut(module=m, permissions=perms) for m, perms in groups.items()]


def get_role_permissions(db: Session, role_id: int) -> RolePermissionsOut:
    role = get_role(db, role_id)
    return RolePermissionsOut(role_id=role.id, codes=sorted(p.code for p in role.permissions))


def set_role_permissions(
    db: Session, actor: User, role_id: int, codes: list[str], request: Request | None = None
) -> RolePermissionsOut:
    """Replace the role's permissions with exactly `codes`. Takes effect on the next request."""
    role = get_role(db, role_id, lock=True)
    wanted = set(codes)
    found = list(db.scalars(select(Permission).where(Permission.code.in_(wanted))))
    unknown = wanted - {p.code for p in found}
    if unknown:
        raise AppError(
            400, "UNKNOWN_PERMISSION", f"Unknown permission: {', '.join(sorted(unknown))}"
        )
    if role.name == ADMIN_ROLE:
        total = db.scalar(select(func.count()).select_from(Permission))
        if len(found) != total:
            raise AppError(
                400, "ADMIN_PERMISSIONS_LOCKED", "The Admin role must keep every permission"
            )

    before = {p.code for p in role.permissions}
    role.permissions = found
    added, removed = sorted(wanted - before), sorted(before - wanted)
    if added or removed:
        log_audit(
            db,
            actor,
            "update",
            "role",
            role.id,
            f"Changed permissions of {role.name}: +{len(added)} / -{len(removed)}",
            old={"removed": removed},
            new={"added": added},
            request=request,
        )
    db.commit()
    return RolePermissionsOut(role_id=role.id, codes=sorted(wanted))


# =========================================================================================
# Audit log (read-only)
# =========================================================================================


def list_audit_logs(
    db: Session,
    params: PageParams,
    date_from: date | None,
    date_to: date | None,
    user_id: int | None,
    entity_type: str | None,
    action: str | None,
    entity_id: str | None,
) -> dict[str, Any]:
    stmt = select(AuditLog).options(selectinload(AuditLog.user)).order_by(AuditLog.id.desc())
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= local_day_start_utc(date_from))
    if date_to:
        stmt = stmt.where(AuditLog.created_at < local_day_end_utc(date_to))
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if params.search:
        stmt = stmt.where(AuditLog.summary.contains(params.search, autoescape=True))
    page = paginate(db, stmt, params)
    page["items"] = [
        AuditLogOut(
            id=a.id,
            user_id=a.user_id,
            user_name=a.user.full_name if a.user else None,
            action=a.action,
            entity_type=a.entity_type,
            entity_id=a.entity_id,
            summary=a.summary,
            old_values=a.old_values,
            new_values=a.new_values,
            ip_address=a.ip_address,
            created_at=a.created_at,
        )
        for a in page["items"]
    ]
    return page


def audit_facets(db: Session) -> AuditFacetsOut:
    return AuditFacetsOut(
        entity_types=list(
            db.scalars(select(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type))
        ),
        actions=list(db.scalars(select(AuditLog.action).distinct().order_by(AuditLog.action))),
    )


# =========================================================================================
# Company settings
# =========================================================================================

_COMPANY_FIELDS = list(CompanySettingsIn.model_fields)


def get_company_settings(db: Session) -> CompanySetting:
    row = db.get(CompanySetting, COMPANY_SETTINGS_ID)
    if row is None:  # normally created by the migration
        row = CompanySetting(id=COMPANY_SETTINGS_ID)
        db.add(row)
        db.flush()
        db.refresh(row)
    return row


def update_company_settings(
    db: Session, actor: User, data: CompanySettingsIn, request: Request | None = None
) -> CompanySetting:
    try:
        ZoneInfo(data.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise AppError(400, "INVALID_TIMEZONE", f"Unknown time zone: {data.timezone}") from exc

    row = get_company_settings(db)
    new = data.model_dump()
    old = {f: getattr(row, f) for f in _COMPANY_FIELDS}
    changed = [f for f in _COMPANY_FIELDS if old[f] != new[f]]
    for f in changed:
        setattr(row, f, new[f])
    if changed:
        log_audit(
            db,
            actor,
            "update",
            "company_setting",
            row.id,
            f"Updated company settings: {', '.join(changed)}",
            old={f: old[f] for f in changed},
            new={f: new[f] for f in changed},
            request=request,
        )
    db.commit()
    db.refresh(row)
    return row


# =========================================================================================
# Document sequences
# =========================================================================================


def sequence_out(seq: DocumentSequence) -> DocumentSequenceOut:
    return DocumentSequenceOut(
        id=seq.id,
        doc_type=seq.doc_type,
        label=DOC_TYPE_LABELS.get(seq.doc_type, seq.doc_type),
        prefix=seq.prefix,
        padding=seq.padding,
        next_number=seq.next_number,
        preview=format_number(seq.prefix, seq.padding, seq.next_number),
    )


def list_sequences(db: Session, params: PageParams) -> dict[str, Any]:
    stmt = select(DocumentSequence).order_by(DocumentSequence.id)
    if params.search:
        stmt = stmt.where(DocumentSequence.doc_type.contains(params.search, autoescape=True))
    page = paginate(db, stmt, params)
    page["items"] = [sequence_out(s) for s in page["items"]]
    return page


def update_sequence(
    db: Session, actor: User, seq_id: int, data: DocumentSequenceIn, request: Request | None = None
) -> DocumentSequenceOut:
    seq = db.scalar(select(DocumentSequence).where(DocumentSequence.id == seq_id).with_for_update())
    if seq is None:
        raise AppError(404, "SEQUENCE_NOT_FOUND", "Document sequence not found")
    if data.next_number < seq.next_number:
        raise AppError(
            400,
            "SEQUENCE_DECREASE",
            f"Next number can only go up (currently {seq.next_number}); "
            "lowering it could create duplicate document numbers",
        )
    old = {"prefix": seq.prefix, "padding": seq.padding, "next_number": seq.next_number}
    new = data.model_dump()
    if old != new:
        seq.prefix, seq.padding, seq.next_number = data.prefix, data.padding, data.next_number
        log_audit(
            db,
            actor,
            "update",
            "document_sequence",
            seq.id,
            f"Updated {seq.doc_type} numbering: next {sequence_out(seq).preview}",
            old=old,
            new=new,
            request=request,
        )
    db.commit()
    return sequence_out(seq)
