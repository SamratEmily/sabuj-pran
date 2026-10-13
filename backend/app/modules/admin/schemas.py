from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints

from app.core.schemas import UtcDateTime
from app.modules.auth.schemas import FullName, OptionalEmail, OptionalMobile, Password

Username = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9_.-]{3,50}$")
]
RoleName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)]


# --- users -----------------------------------------------------------------------------


class UserAdminOut(BaseModel):
    id: int
    full_name: str
    username: str
    email: str | None
    mobile: str | None
    role_id: int
    role_name: str
    is_active: bool
    must_change_password: bool
    last_login_at: UtcDateTime | None
    created_at: UtcDateTime


class UserUpdateIn(BaseModel):
    full_name: FullName
    email: OptionalEmail = None
    mobile: OptionalMobile = None
    role_id: int


class UserCreateIn(UserUpdateIn):
    username: Username
    password: Password
    must_change_password: bool = True


class UserPasswordResetIn(BaseModel):
    password: Password


# --- roles & permissions ---------------------------------------------------------------


class RoleOut(BaseModel):
    id: int
    name: str
    description: str
    is_system: bool
    user_count: int
    permission_count: int


class RoleIn(BaseModel):
    name: RoleName
    description: ShortText = ""


class PermissionOut(BaseModel):
    code: str
    description: str


class PermissionGroupOut(BaseModel):
    module: str
    permissions: list[PermissionOut]


class RolePermissionsIn(BaseModel):
    codes: list[str] = Field(max_length=1000)


class RolePermissionsOut(BaseModel):
    role_id: int
    codes: list[str]


# --- audit log -------------------------------------------------------------------------


class AuditLogOut(BaseModel):
    id: int
    user_id: int | None
    user_name: str | None
    action: str
    entity_type: str
    entity_id: str | None
    summary: str
    old_values: dict[str, Any] | None
    new_values: dict[str, Any] | None
    ip_address: str | None
    created_at: UtcDateTime


class AuditFacetsOut(BaseModel):
    entity_types: list[str]
    actions: list[str]


# --- company settings ------------------------------------------------------------------


class CompanySettingsIn(BaseModel):
    company_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=150)] = ""
    address: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=30)] = ""
    email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=150)] = ""
    currency_symbol: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10)
    ] = "BDT"
    timezone: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)
    ] = "Asia/Dhaka"
    invoice_footer_note: Annotated[str, StringConstraints(max_length=500)] = ""
    logo_url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""


class CompanySettingsOut(CompanySettingsIn):
    updated_at: UtcDateTime


# --- document sequences ----------------------------------------------------------------


class DocumentSequenceOut(BaseModel):
    id: int
    doc_type: str
    label: str
    prefix: str
    padding: int
    next_number: int
    preview: str


class DocumentSequenceIn(BaseModel):
    prefix: Annotated[str, StringConstraints(max_length=20, pattern=r"^[A-Za-z0-9/_-]*$")]
    padding: Annotated[int, Field(ge=1, le=12)]
    next_number: Annotated[int, Field(ge=1, le=2_000_000_000)]
