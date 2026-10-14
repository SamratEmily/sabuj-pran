from fastapi.testclient import TestClient


def test_health_reports_db_ok(client: TestClient) -> None:
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "db": True}


def test_unknown_route_uses_error_shape(client: TestClient) -> None:
    res = client.get("/api/v1/does-not-exist")
    assert res.status_code == 404
    assert res.json() == {"detail": "Not Found", "code": "NOT_FOUND"}


def test_unique_key_race_is_a_409_not_a_500() -> None:
    """An IntegrityError that slips past a service pre-check renders as a clean conflict."""
    import asyncio
    import json

    from sqlalchemy.exc import IntegrityError

    from app.core.errors import integrity_error_handler

    exc = IntegrityError("INSERT ...", {}, Exception("Duplicate entry 'x' for key 'uq'"))
    res = asyncio.run(integrity_error_handler(None, exc))  # type: ignore[arg-type]
    assert res.status_code == 409
    assert json.loads(res.body)["code"] == "CONFLICT"
