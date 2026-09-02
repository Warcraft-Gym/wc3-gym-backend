"""An uploaded map picture goes to Vercel Blob, the way a team logo does.

The blob store is stubbed by the `blob_store` fixture in conftest, so nothing here reaches Vercel.
"""

from typing import Any

from httpx2 import Client, Response

from app.core.db import Session
from app.models.map import Map

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
PUBLISHED = "https://d3upx5peno0o6w.cloudfront.net/echo.png"


def upload(
    client: Client, map_id: int, headers: dict[str, str], data: bytes
) -> Response:
    return client.post(
        f"/maps/{map_id}/image",
        files={"image": ("map.png", data, "image/png")},
        headers=headers,
    )


def test_an_upload_lands_in_the_store_and_the_row_points_at_it(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    blob_store: dict[str, bytes],
) -> None:
    assert upload(client, seeded["map_id"], auth_headers, PNG).status_code == 200

    assert list(blob_store.values()) == [PNG]
    url = next(iter(blob_store))
    assert client.get(f"/maps/{seeded['map_id']}").json()["image"] == url
    hop = client.get(f"/maps/{seeded['map_id']}/image", follow_redirects=False)
    assert hop.status_code == 307
    assert hop.headers["location"] == url


def test_a_replacement_drops_the_blob_it_replaced(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    blob_store: dict[str, bytes],
) -> None:
    upload(client, seeded["map_id"], auth_headers, PNG)
    first = next(iter(blob_store))

    upload(client, seeded["map_id"], auth_headers, PNG + b"second")

    assert first not in blob_store
    assert list(blob_store.values()) == [PNG + b"second"]


def test_a_published_picture_is_replaced_but_never_deleted(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    blob_store: dict[str, bytes],
) -> None:
    """warcraft3.info hosts what the ladder import found. It is not ours to delete."""
    with Session.begin() as session:
        Map.update(session, seeded["map_id"], image=PUBLISHED)

    assert upload(client, seeded["map_id"], auth_headers, PNG).status_code == 200

    assert client.get(f"/maps/{seeded['map_id']}").json()["image"] != PUBLISHED
    assert list(blob_store.values()) == [PNG]


def test_something_that_is_not_a_png_is_refused(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    blob_store: dict[str, bytes],
) -> None:
    resp = upload(client, seeded["map_id"], auth_headers, b"GIF89a" + b"0" * 64)
    assert resp.status_code == 400
    assert not blob_store, "a refused upload must not reach the store"
    assert client.get(f"/maps/{seeded['map_id']}").json()["image"] is None
