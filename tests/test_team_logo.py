"""A team logo becomes a public URL, so what the upload accepts is checked here.

The blob store is stubbed by the `blob_store` fixture in conftest, so nothing here reaches Vercel.
"""

from typing import Any

import pytest
from httpx2 import Client, Response

from app.core.exceptions import BadRequestError
from app.services import blob

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
# bound at collection, before the blob_store fixture replaces the module attribute
REAL_PUT_ICON = blob.put_icon


def upload(
    client: Client, team_id: int, headers: dict[str, str], data: bytes
) -> Response:
    return client.post(
        f"/teams/{team_id}/image",
        files={"image": ("icon.png", data, "image/png")},
        headers=headers,
    )


def test_a_png_is_accepted(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    blob_store: dict[str, bytes],
) -> None:
    resp = upload(client, seeded["team_a_id"], auth_headers, PNG)
    assert resp.status_code == 200
    assert list(blob_store.values()) == [PNG]


def test_something_that_is_not_a_png_is_refused(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    blob_store: dict[str, bytes],
) -> None:
    resp = upload(client, seeded["team_a_id"], auth_headers, b"GIF89a" + b"0" * 64)
    assert resp.status_code == 400
    assert not blob_store, "a refused upload must not reach the store"


def test_an_oversized_image_is_refused(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    blob_store: dict[str, bytes],
) -> None:
    too_big = PNG + b"0" * blob.MAX_ICON_BYTES
    resp = upload(client, seeded["team_a_id"], auth_headers, too_big)
    assert resp.status_code == 400
    assert not blob_store


def test_replacing_a_logo_drops_the_one_it_replaces(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    blob_store: dict[str, bytes],
) -> None:
    team_id = seeded["team_a_id"]
    upload(client, team_id, auth_headers, PNG)
    second = PNG + b"second"
    upload(client, team_id, auth_headers, second)
    assert list(blob_store.values()) == [second], (
        "the replaced logo should not be left behind"
    )


def test_the_team_answer_carries_the_logo_url(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    blob_store: dict[str, bytes],
) -> None:
    team_id = seeded["team_a_id"]
    assert client.get(f"/teams/{team_id}").json()["icon_url"] is None
    upload(client, team_id, auth_headers, PNG)
    url = client.get(f"/teams/{team_id}").json()["icon_url"]
    assert blob_store[url] == PNG


@pytest.mark.parametrize("data", [b"", b"not an image at all"])
def test_icon_type_refuses_junk(data: bytes) -> None:
    with pytest.raises(BadRequestError):
        blob.icon_type(data)


def test_a_jpeg_is_accepted(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    blob_store: dict[str, bytes],
) -> None:
    """Three of the ten production logos are JPEGs that were stored as image/png."""
    resp = upload(client, seeded["team_a_id"], auth_headers, JPEG)
    assert resp.status_code == 200
    assert list(blob_store.values()) == [JPEG]


def test_put_icon_follows_the_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The conftest stub replaces put_icon wholesale, so the pathname and content type it chooses
    are only covered here, by standing in for the SDK instead."""
    from vercel import blob as sdk

    seen: dict[str, object] = {}

    class Result:
        url = "https://blob.test/x"

    def fake_put(path: str, body: bytes, **kwargs: object) -> Result:
        seen["path"] = path
        seen["content_type"] = kwargs["content_type"]
        return Result()

    monkeypatch.setattr(sdk, "put", fake_put)
    REAL_PUT_ICON(7, JPEG)
    assert seen == {"path": "teams/7.jpg", "content_type": "image/jpeg"}

    REAL_PUT_ICON(7, PNG)
    assert seen == {"path": "teams/7.png", "content_type": "image/png"}


def test_the_image_route_redirects_once_a_logo_is_in_the_store(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    blob_store: dict[str, bytes],
) -> None:
    team_id = seeded["team_a_id"]
    upload(client, team_id, auth_headers, PNG)
    resp = client.get(f"/teams/{team_id}/image", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] in blob_store
    # a replacement deletes the blob this points at, so a cached redirect would 404 for its lifetime
    assert resp.headers["cache-control"] == "no-store"


def test_a_team_with_no_logo_at_all_answers_not_found(
    client: Client, seeded: dict[str, Any]
) -> None:
    assert client.get(f"/teams/{seeded['team_a_id']}/image").status_code == 404
