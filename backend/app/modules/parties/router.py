from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.core.deps import Allow, DbDep
from app.core.pagination import Page, PageParamsDep
from app.modules.parties import service
from app.modules.parties.schemas import PartyIn, PartyOut, StatementOut
from app.modules.parties.service import PartyKind

router = APIRouter()


def _party_routes(prefix: str, kind: PartyKind) -> None:
    """CRUD + statement for customers or suppliers. Permissions: `<party_type>.*`;
    statements need `party_statement.view`."""
    perm = kind.party_type
    r = APIRouter(prefix=prefix, tags=[prefix.strip("/")])

    @r.get("")
    def list_(
        db: DbDep, params: PageParamsDep, _: Allow(f"{perm}.view"), is_active: bool | None = None
    ) -> Page[PartyOut]:
        return Page[PartyOut](**service.list_parties(db, kind, params, is_active))

    @r.post("", status_code=201)
    def create(
        data: PartyIn, db: DbDep, actor: Allow(f"{perm}.create"), request: Request
    ) -> PartyOut:
        return service.create_party(db, actor, kind, data, request)

    @r.get("/{party_id}")
    def get(party_id: int, db: DbDep, _: Allow(f"{perm}.view")) -> PartyOut:
        return service.party_out(db, kind, service.get_party(db, kind, party_id))

    @r.put("/{party_id}")
    def update(
        party_id: int, data: PartyIn, db: DbDep, actor: Allow(f"{perm}.edit"), request: Request
    ) -> PartyOut:
        return service.update_party(db, actor, kind, party_id, data, request)

    @r.post("/{party_id}/deactivate")
    def deactivate(
        party_id: int, db: DbDep, actor: Allow(f"{perm}.delete"), request: Request
    ) -> PartyOut:
        return service.set_party_active(db, actor, kind, party_id, False, request)

    @r.post("/{party_id}/activate")
    def activate(
        party_id: int, db: DbDep, actor: Allow(f"{perm}.delete"), request: Request
    ) -> PartyOut:
        return service.set_party_active(db, actor, kind, party_id, True, request)

    @r.get("/{party_id}/statement")
    def statement(
        party_id: int,
        db: DbDep,
        _: Allow("party_statement.view"),
        date_from: Annotated[date | None, Query(alias="from")] = None,
        date_to: Annotated[date | None, Query(alias="to")] = None,
    ) -> StatementOut:
        return service.get_statement(db, kind.party_type, party_id, date_from, date_to)

    router.include_router(r)


_party_routes("/customers", service.CUSTOMERS)
_party_routes("/suppliers", service.SUPPLIERS)
