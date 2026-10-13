from datetime import timedelta
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db, utcnow
from app.core.deps import require_permission
from app.core.security import verify_password
from app.main import create_app
from app.modules.auth.models import AuditLog, PasswordResetToken, Role, User, role_permissions
from app.seed import DEMO_USERS, seed
from tests.conftest import TEST_PASSWORD, MakeUser, auth_headers

LOGIN = "/api/v1/auth/login"


def login(client: TestClient, identifier: str, password: str = TEST_PASSWORD):
    return client.post(LOGIN, json={"identifier": identifier, "password": password})


# --- login ---------------------------------------------------------------------------


@pytest.mark.parametrize("identifier", ["alice", "alice@example.com", "01711000001"])
def test_login_by_username_email_or_mobile(
    client: TestClient, db: Session, make_user: MakeUser, identifier: str
) -> None:
    user = make_user("alice", ["product.view"], email="alice@example.com", mobile="01711000001")

    res = login(client, identifier)

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["access_token"]
    assert body["user"]["id"] == user.id
    assert body["user"]["permissions"] == ["product.view"]
    assert body["user"]["role"] == "role-alice"
    db.refresh(user)
    assert user.last_login_at is not None
    audit = db.scalar(select(AuditLog).where(AuditLog.user_id == user.id))
    assert audit is not None and audit.action == "login"


def test_login_wrong_password(client: TestClient, make_user: MakeUser) -> None:
    make_user("bob")
    res = login(client, "bob", "wrong-password")
    assert res.status_code == 401
    assert res.json()["code"] == "INVALID_CREDENTIALS"


def test_login_unknown_user_looks_like_wrong_password(client: TestClient) -> None:
    res = login(client, "nobody")
    assert res.status_code == 401
    assert res.json()["code"] == "INVALID_CREDENTIALS"


def test_login_inactive_user(client: TestClient, make_user: MakeUser) -> None:
    make_user("carol", is_active=False)
    res = login(client, "carol")
    assert res.status_code == 403
    assert res.json()["code"] == "USER_INACTIVE"


def test_token_of_deactivated_user_is_rejected(
    client: TestClient, db: Session, make_user: MakeUser
) -> None:
    user = make_user("dave")
    headers = auth_headers(user)
    user.is_active = False
    db.flush()
    res = client.get("/api/v1/auth/me", headers=headers)
    assert res.status_code == 401


def test_me_requires_token(client: TestClient) -> None:
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401
    assert res.json()["code"] == "NOT_AUTHENTICATED"


def test_garbage_token(client: TestClient) -> None:
    res = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert res.status_code == 401
    assert res.json()["code"] == "INVALID_TOKEN"


# --- permissions ---------------------------------------------------------------------


@pytest.fixture
def protected_client(db: Session) -> TestClient:
    router = APIRouter()

    @router.get("/api/v1/_test/products")
    def products(
        _: Annotated[User, Depends(require_permission("product.view"))],
    ) -> dict[str, bool]:
        return {"ok": True}

    test_app = create_app()
    test_app.include_router(router)
    test_app.dependency_overrides[get_db] = lambda: db
    return TestClient(test_app)


def test_permission_denied_without_permission(
    protected_client: TestClient, make_user: MakeUser
) -> None:
    user = make_user("nopriv", ["customer.view"])
    res = protected_client.get("/api/v1/_test/products", headers=auth_headers(user))
    assert res.status_code == 403
    assert res.json()["code"] == "PERMISSION_DENIED"


def test_permission_granted_with_permission(
    protected_client: TestClient, make_user: MakeUser
) -> None:
    user = make_user("priv", ["product.view"])
    res = protected_client.get("/api/v1/_test/products", headers=auth_headers(user))
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_unknown_permission_code_fails_fast() -> None:
    with pytest.raises(ValueError):
        require_permission("product.fly")


# --- profile ---------------------------------------------------------------------------


def test_update_profile(client: TestClient, make_user: MakeUser) -> None:
    user = make_user("erin")
    res = client.put(
        "/api/v1/auth/me",
        headers=auth_headers(user),
        json={"full_name": "Erin New", "email": "erin@example.com", "mobile": ""},
    )
    assert res.status_code == 200, res.text
    assert res.json()["full_name"] == "Erin New"
    assert res.json()["email"] == "erin@example.com"
    assert res.json()["mobile"] is None


def test_update_profile_duplicate_email(client: TestClient, make_user: MakeUser) -> None:
    make_user("frank", email="taken@example.com")
    user = make_user("gina")
    res = client.put(
        "/api/v1/auth/me",
        headers=auth_headers(user),
        json={"full_name": "Gina", "email": "taken@example.com"},
    )
    assert res.status_code == 409
    assert res.json()["code"] == "EMAIL_TAKEN"


# --- change password -------------------------------------------------------------------


def test_change_password(client: TestClient, make_user: MakeUser) -> None:
    user = make_user("hank", must_change_password=True)
    headers = auth_headers(user)

    wrong = client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"current_password": "nope", "new_password": "NewPassw0rd!"},
    )
    assert wrong.status_code == 400
    assert wrong.json()["code"] == "INVALID_CURRENT_PASSWORD"

    same = client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"current_password": TEST_PASSWORD, "new_password": TEST_PASSWORD},
    )
    assert same.status_code == 400
    assert same.json()["code"] == "PASSWORD_UNCHANGED"

    short = client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"current_password": TEST_PASSWORD, "new_password": "short"},
    )
    assert short.status_code == 422

    ok = client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"current_password": TEST_PASSWORD, "new_password": "NewPassw0rd!"},
    )
    assert ok.status_code == 200
    assert login(client, "hank").status_code == 401
    relogin = login(client, "hank", "NewPassw0rd!")
    assert relogin.status_code == 200
    assert relogin.json()["user"]["must_change_password"] is False


# --- forgot / reset password -----------------------------------------------------------


def test_forgot_and_reset_password_flow(
    client: TestClient, db: Session, make_user: MakeUser
) -> None:
    user = make_user("ivy", email="ivy@example.com")

    res = client.post("/api/v1/auth/forgot-password", json={"identifier": "ivy@example.com"})
    assert res.status_code == 200
    token = res.json()["reset_token"]
    stored = db.scalar(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    assert stored is not None and stored.token_hash != token  # only the hash is stored

    reset = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": "ResetPass1!"}
    )
    assert reset.status_code == 200, reset.text
    assert login(client, "ivy", "ResetPass1!").status_code == 200

    reuse = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": "Another1!x"}
    )
    assert reuse.status_code == 400
    assert reuse.json()["code"] == "INVALID_RESET_TOKEN"
    db.refresh(user)
    assert verify_password("ResetPass1!", user.password_hash)


def test_forgot_password_unknown_identifier_is_generic(client: TestClient) -> None:
    res = client.post("/api/v1/auth/forgot-password", json={"identifier": "ghost"})
    assert res.status_code == 200
    assert res.json() == {
        "message": "If an account matches, password reset instructions have been sent."
    }


def test_forgot_password_hides_token_in_production(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_user("jack")
    monkeypatch.setattr(settings, "app_env", "production")
    res = client.post("/api/v1/auth/forgot-password", json={"identifier": "jack"})
    assert res.status_code == 200
    assert "reset_token" not in res.json()


def test_expired_reset_token_rejected(client: TestClient, db: Session, make_user: MakeUser) -> None:
    make_user("kate")
    token = client.post("/api/v1/auth/forgot-password", json={"identifier": "kate"}).json()[
        "reset_token"
    ]
    row = db.scalar(select(PasswordResetToken).order_by(PasswordResetToken.id.desc()))
    assert row is not None
    row.expires_at = utcnow() - timedelta(seconds=1)
    db.flush()

    res = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": "ResetPass1!"}
    )
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_RESET_TOKEN"


# --- logout ----------------------------------------------------------------------------


def test_logout_is_audited(client: TestClient, db: Session, make_user: MakeUser) -> None:
    user = make_user("leo")
    res = client.post("/api/v1/auth/logout", headers=auth_headers(user))
    assert res.status_code == 200
    actions = db.scalars(select(AuditLog.action).where(AuditLog.user_id == user.id)).all()
    assert actions == ["logout"]


# --- seed ------------------------------------------------------------------------------


def _counts(db: Session) -> tuple[int, int, int]:
    return (
        db.scalar(select(func.count()).select_from(Role)) or 0,
        db.scalar(select(func.count()).select_from(User)) or 0,
        db.scalar(select(func.count()).select_from(role_permissions)) or 0,
    )


def test_seed_is_idempotent(client: TestClient, db: Session) -> None:
    seed(db)
    first = _counts(db)
    seed(db)
    assert _counts(db) == first
    assert first[1] == len(DEMO_USERS)

    res = login(client, "admin", "Admin@123")
    assert res.status_code == 200
    assert "approval.approve" in res.json()["user"]["permissions"]

    sales = login(client, "sales", "Admin@123").json()["user"]["permissions"]
    assert "invoice.create" in sales and "purchase_order.view" not in sales
