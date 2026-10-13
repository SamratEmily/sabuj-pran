import logging
from datetime import timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.config import settings
from app.core.db import utcnow
from app.core.errors import AppError
from app.core.permissions import PERMISSION_DEFINITIONS
from app.core.security import (
    create_access_token,
    dummy_password_hash,
    generate_reset_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.modules.auth.models import PasswordResetToken, Permission, Role, User
from app.modules.auth.schemas import (
    ChangePasswordIn,
    ForgotPasswordOut,
    LoginIn,
    LoginOut,
    ProfileUpdateIn,
    ResetPasswordIn,
    UserOut,
)

logger = logging.getLogger(__name__)

ADMIN_ROLE = "Admin"
RESET_TOKEN_TTL = timedelta(minutes=30)
FORGOT_MESSAGE = "If an account matches, password reset instructions have been sent."
UNIQUE_PROFILE_FIELDS = (("email", "EMAIL_TAKEN", "Email"), ("mobile", "MOBILE_TAKEN", "Mobile"))


def sync_permissions(db: Session) -> int:
    """Insert permission codes missing from the table (never deletes) and grant them to Admin.

    Returns the number of permissions inserted. Does not commit.
    """
    existing = {p.code: p for p in db.scalars(select(Permission))}
    added = [
        Permission(code=code, module=module, description=description)
        for code, (module, description) in PERMISSION_DEFINITIONS.items()
        if code not in existing
    ]
    db.add_all(added)
    admin = db.scalar(select(Role).where(Role.name == ADMIN_ROLE))
    if admin is not None:
        granted = {p.code for p in admin.permissions}
        admin.permissions.extend(p for p in [*existing.values(), *added] if p.code not in granted)
    db.flush()
    return len(added)


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        full_name=user.full_name,
        username=user.username,
        email=user.email,
        mobile=user.mobile,
        role=user.role.name,
        permissions=sorted(user.permission_codes),
        must_change_password=user.must_change_password,
    )


def find_by_identifier(db: Session, identifier: str) -> User | None:
    """Match username first, then email, then mobile."""
    for column in (User.username, User.email, User.mobile):
        user = db.scalar(select(User).where(column == identifier))
        if user is not None:
            return user
    return None


def login(db: Session, data: LoginIn, request: Request | None = None) -> LoginOut:
    user = find_by_identifier(db, data.identifier)
    if user is None:
        verify_password(data.password, dummy_password_hash())
        raise AppError(401, "INVALID_CREDENTIALS", "Invalid username or password")
    if not verify_password(data.password, user.password_hash):
        raise AppError(401, "INVALID_CREDENTIALS", "Invalid username or password")
    if not user.is_active:
        raise AppError(403, "USER_INACTIVE", "This account is inactive")

    user.last_login_at = utcnow()
    log_audit(db, user, "login", "user", user.id, f"{user.username} logged in", request=request)
    db.commit()
    return LoginOut(
        access_token=create_access_token(user.id),
        expires_in=settings.access_token_expire_minutes * 60,
        user=user_out(user),
    )


def logout(db: Session, user: User, request: Request | None = None) -> None:
    log_audit(db, user, "logout", "user", user.id, f"{user.username} logged out", request=request)
    db.commit()


def update_profile(
    db: Session, user: User, data: ProfileUpdateIn, request: Request | None = None
) -> UserOut:
    for field, code, label in UNIQUE_PROFILE_FIELDS:
        value = getattr(data, field)
        column = getattr(User, field)
        if value is not None and db.scalar(
            select(User.id).where(column == value, User.id != user.id)
        ):
            raise AppError(409, code, f"{label} is already used by another user")

    old = {"full_name": user.full_name, "email": user.email, "mobile": user.mobile}
    new = data.model_dump()
    for field, value in new.items():
        setattr(user, field, value)
    log_audit(db, user, "update", "user", user.id, "Updated own profile", old, new, request)
    db.commit()
    return user_out(user)


def _set_password(user: User, new_password: str) -> None:
    user.password_hash = hash_password(new_password)
    user.must_change_password = False


def change_password(
    db: Session, user: User, data: ChangePasswordIn, request: Request | None = None
) -> None:
    if not verify_password(data.current_password, user.password_hash):
        raise AppError(400, "INVALID_CURRENT_PASSWORD", "Current password is incorrect")
    if data.new_password == data.current_password:
        raise AppError(
            400, "PASSWORD_UNCHANGED", "New password must be different from the current one"
        )
    _set_password(user, data.new_password)
    log_audit(db, user, "update", "user", user.id, "Changed password", request=request)
    db.commit()


def forgot_password(db: Session, identifier: str) -> ForgotPasswordOut:
    user = find_by_identifier(db, identifier)
    if user is None or not user.is_active:
        return ForgotPasswordOut(message=FORGOT_MESSAGE)

    raw, token_hash = generate_reset_token()
    db.add(
        PasswordResetToken(
            user_id=user.id, token_hash=token_hash, expires_at=utcnow() + RESET_TOKEN_TTL
        )
    )
    db.commit()

    if settings.is_production:
        return ForgotPasswordOut(message=FORGOT_MESSAGE)
    # No email gateway: expose the token outside production only.
    logger.warning("Password reset token for %s: %s", user.username, raw)
    return ForgotPasswordOut(message=FORGOT_MESSAGE, reset_token=raw)


def reset_password(db: Session, data: ResetPasswordIn, request: Request | None = None) -> None:
    token = db.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == hash_token(data.token))
        .with_for_update()
    )
    now = utcnow()
    if token is None or token.used_at is not None or token.expires_at <= now:
        raise AppError(400, "INVALID_RESET_TOKEN", "Reset link is invalid or has expired")
    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise AppError(400, "INVALID_RESET_TOKEN", "Reset link is invalid or has expired")

    token.used_at = now
    _set_password(user, data.new_password)
    log_audit(db, user, "update", "user", user.id, "Reset password via token", request=request)
    db.commit()
