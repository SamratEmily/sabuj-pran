import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import bcrypt
import jwt

from app.core.config import settings
from app.core.errors import AppError


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=settings.bcrypt_rounds)
    return bcrypt.hashpw(password.encode(), salt).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:  # malformed hash or password over bcrypt's 72-byte limit
        return False


@lru_cache
def dummy_password_hash() -> str:
    """Checked against when the user is unknown, so timing matches a wrong password."""
    return hash_password(secrets.token_urlsafe(16))


def create_access_token(user_id: int) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AppError(401, "TOKEN_EXPIRED", "Session expired. Please log in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise AppError(401, "INVALID_TOKEN", "Invalid authentication token") from exc
    if payload.get("type") != "access":
        raise AppError(401, "INVALID_TOKEN", "Invalid authentication token")
    return payload


def generate_reset_token() -> tuple[str, str]:
    """Returns (raw token for the user, sha256 hash to store)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
