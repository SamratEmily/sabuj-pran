from fastapi import APIRouter, Request

from app.core.deps import CurrentUser, DbDep
from app.modules.auth import service
from app.modules.auth.schemas import (
    ChangePasswordIn,
    ForgotPasswordIn,
    ForgotPasswordOut,
    LoginIn,
    LoginOut,
    MessageOut,
    ProfileUpdateIn,
    ResetPasswordIn,
    UserOut,
)

# /me, /change-password and /logout need authentication only: every user manages their own account.
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(data: LoginIn, db: DbDep, request: Request) -> LoginOut:
    return service.login(db, data, request)


@router.get("/me")
def me(user: CurrentUser) -> UserOut:
    return service.user_out(user)


@router.put("/me")
def update_me(data: ProfileUpdateIn, db: DbDep, user: CurrentUser, request: Request) -> UserOut:
    return service.update_profile(db, user, data, request)


@router.post("/change-password")
def change_password(
    data: ChangePasswordIn, db: DbDep, user: CurrentUser, request: Request
) -> MessageOut:
    service.change_password(db, user, data, request)
    return MessageOut(message="Password changed")


@router.post("/forgot-password", response_model_exclude_none=True)
def forgot_password(data: ForgotPasswordIn, db: DbDep) -> ForgotPasswordOut:
    return service.forgot_password(db, data.identifier)


@router.post("/reset-password")
def reset_password(data: ResetPasswordIn, db: DbDep, request: Request) -> MessageOut:
    service.reset_password(db, data, request)
    return MessageOut(message="Password has been reset. You can now log in.")


@router.post("/logout")
def logout(db: DbDep, user: CurrentUser, request: Request) -> MessageOut:
    service.logout(db, user, request)
    return MessageOut(message="Logged out")
