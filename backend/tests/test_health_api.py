"""Contract test for the process liveness endpoint."""

from httpx import AsyncClient


async def test_liveness_returns_success_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"
    assert body["data"]["environment"] == "local"
