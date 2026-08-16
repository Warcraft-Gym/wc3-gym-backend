"""The health route answers 200 when the database answers."""

from httpx2 import Client


def test_health_answers_ok(client: Client) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
