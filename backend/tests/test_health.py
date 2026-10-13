from fastapi.testclient import TestClient


def test_health_reports_db_ok(client: TestClient) -> None:
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "db": True}


def test_unknown_route_uses_error_shape(client: TestClient) -> None:
    res = client.get("/api/v1/does-not-exist")
    assert res.status_code == 404
    assert res.json() == {"detail": "Not Found", "code": "NOT_FOUND"}
