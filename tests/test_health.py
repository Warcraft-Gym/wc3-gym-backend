"""The health route answers 200 when the database answers, and the root sends
a visitor to the documentation."""

from httpx2 import Client


def test_health_answers_ok(client: Client) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_the_root_sends_a_visitor_to_the_docs(client: Client) -> None:
    """The only route with nothing behind it: a person who opens the API host
    lands on the documentation."""
    resp = client.get("/")

    assert resp.status_code == 302
    assert resp.headers["location"] == "/docs"


def test_the_docs_answer(client: Client) -> None:
    resp = client.get("/docs")

    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
