"""Contract tests for the Phase 0 health endpoints."""


async def test_liveness_returns_success_envelope(client) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"
    assert body["data"]["environment"] == "local"


async def test_ready_checks_database(client) -> None:
    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"] == {"status": "ready", "database": "ok"}
