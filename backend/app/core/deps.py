from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError
from app.core.permissions import PERMISSION_SET
from app.core.security import decode_access_token
from app.modules.auth.models import User

DbDep = Annotated[Session, Depends(get_db)]

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    db: DbDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise AppError(401, "NOT_AUTHENTICATED", "Not authenticated")
    payload = decode_access_token(credentials.credentials)
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError) as exc:
        raise AppError(401, "INVALID_TOKEN", "Invalid authentication token") from exc
    user = db.get(User, user_id)
    if user is None:
        raise AppError(401, "INVALID_TOKEN", "Invalid authentication token")
    if not user.is_active:
        raise AppError(401, "USER_INACTIVE", "This account is inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(code: str) -> Callable[[User], User]:
    """Dependency factory: `user: Annotated[User, Depends(require_permission("product.view"))]`."""
    if code not in PERMISSION_SET:
        raise ValueError(f"Unknown permission code: {code}")

    def checker(user: CurrentUser) -> User:
        if code not in user.permission_codes:
            raise AppError(403, "PERMISSION_DENIED", f"You do not have permission: {code}")
        return user

    return checker


def Allow(code: str) -> Any:  # noqa: N802 - reads like a type in signatures
    """`user: Allow("product.view")` is short for
    `Annotated[User, Depends(require_permission("product.view"))]`."""
    return Annotated[User, Depends(require_permission(code))]
