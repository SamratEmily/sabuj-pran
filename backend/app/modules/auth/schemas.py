from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field, StringConstraints


def _blank_to_none(v: object) -> object:
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


Password = Annotated[str, Field(min_length=8, max_length=72)]
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
Email = Annotated[str, StringConstraints(max_length=150, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
Mobile = Annotated[str, StringConstraints(max_length=20, pattern=r"^\+?[0-9]{6,19}$")]
# Blank strings become None so they don't collide on the unique columns.
OptionalEmail = Annotated[Email | None, BeforeValidator(_blank_to_none)]
OptionalMobile = Annotated[Mobile | None, BeforeValidator(_blank_to_none)]


class LoginIn(BaseModel):
    identifier: Identifier
    password: Annotated[str, Field(min_length=1, max_length=128)]


class UserOut(BaseModel):
    id: int
    full_name: str
    username: str
    email: str | None
    mobile: str | None
    role: str
    permissions: list[str]
    must_change_password: bool


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class ProfileUpdateIn(BaseModel):
    full_name: FullName
    email: OptionalEmail = None
    mobile: OptionalMobile = None


class ChangePasswordIn(BaseModel):
    current_password: Annotated[str, Field(min_length=1, max_length=128)]
    new_password: Password


class ForgotPasswordIn(BaseModel):
    identifier: Identifier


class ForgotPasswordOut(BaseModel):
    message: str
    # Only returned outside production (no email gateway exists).
    reset_token: str | None = None


class ResetPasswordIn(BaseModel):
    token: Annotated[str, Field(min_length=1, max_length=200)]
    new_password: Password


class MessageOut(BaseModel):
    message: str
