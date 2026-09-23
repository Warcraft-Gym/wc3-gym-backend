"""The pictures the app owns, in Vercel Blob: team logos and map thumbnails.

The SDK is imported inside each call, not at module scope: it carries its own httpx and a dozen
other packages, and only the upload route ever needs them. Reads never come here at all, because a
public blob is fetched by the browser straight from the store.

Each environment has its own store: `gnl-media` for production, `gnl-media-staging` for preview
and development. A call authenticates with the Vercel OIDC token and `BLOB_STORE_ID`, both from
the store connection, so an environment can only write to and delete from its own store. On Vercel
the token arrives with each request (VercelHeadersMiddleware hands it to the SDK); a local run
reads `VERCEL_OIDC_TOKEN`, which `vercel env pull` writes.

The store follows the rows: a delete that drops a series, by itself or through the cascade from
its match, season, team or player, drops its replays after the commit, and a deleted team or map
drops its picture. app.core.db registers the listeners with the session.
"""

import logging
import os

import requests
from sqlalchemy import event, or_, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import BadRequestError
from app.models.map import Map
from app.models.match import Match
from app.models.season import Season
from app.models.series import Series
from app.models.series_replay import DBSeriesReplay
from app.models.team import Team
from app.models.user import User
from app.services import r2

logger = logging.getLogger(__name__)

# three of the ten logos in production are JPEGs that were stored and served as image/png;
# browsers sniff the bytes, so nobody noticed. Both are accepted, and each is served as what it is.
MAGIC = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg"}
EXTENSION = {"image/png": "png", "image/jpeg": "jpg"}
MAX_ICON_BYTES = 2 * 1024 * 1024
# a blob never changes under its own URL, because every upload gets a new random suffix
ICON_CACHE_SECONDS = 31_536_000
BLOB_API = "https://vercel.com/api/blob"


def icon_type(data: bytes) -> str:
    """The media type of a logo, refusing anything that is not one. A logo becomes a public URL,
    so this runs before it is stored, not after."""
    if not data:
        raise BadRequestError("No image provided")
    if len(data) > MAX_ICON_BYTES:
        raise BadRequestError(f"Image is larger than {MAX_ICON_BYTES // 1024} KB")
    for magic, media_type in MAGIC.items():
        if data.startswith(magic):
            return media_type
    raise BadRequestError("Image must be a PNG or a JPEG")


def _blob_api(
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    data: bytes | None = None,
    json: dict[str, list[str]] | None = None,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    """One call to the Blob API with the OIDC token. The Python SDK authenticates only with a
    static read-write token, so the two calls are made here the way @vercel/blob makes them:
    the token as the bearer, and the store id beside it, because the token does not name one."""
    from vercel.oidc import get_vercel_oidc_token

    auth = {
        "authorization": f"Bearer {get_vercel_oidc_token()}",
        "x-vercel-blob-store-id": os.environ["BLOB_STORE_ID"].removeprefix("store_"),
        "x-api-version": "11",
    }
    response = requests.request(
        method,
        f"{BLOB_API}{path}",
        params=params,
        data=data,
        json=json,
        headers={**auth, **(headers or {})},
        timeout=30,
    )
    response.raise_for_status()
    return response


def put_icon(name: str, data: bytes) -> str:
    """Store the picture under this name, such as `teams/4`, and answer its public URL."""
    media_type = icon_type(data)
    response = _blob_api(
        "PUT",
        "/",
        params={"pathname": f"{name}.{EXTENSION[media_type]}"},
        data=data,
        headers={
            "x-content-type": media_type,
            "x-vercel-blob-access": "public",
            # a new URL every time, so no browser holds a replaced logo for the cache year
            "x-add-random-suffix": "1",
            "x-cache-control-max-age": str(ICON_CACHE_SECONDS),
        },
    )
    return response.json()["url"]


def ours(url: str) -> bool:
    """Whether we wrote this picture. A map picture can be the url warcraft3.info publishes it
    at, which is not ours to delete."""
    return ".public.blob.vercel-storage.com/" in url


def delete_blob(url: str) -> None:
    """Drop a replaced blob. Deletes are free, and a missing blob is not an error worth raising."""
    from vercel.oidc import VercelOidcTokenError

    try:
        _blob_api("POST", "/delete", json={"urls": [url]})
    except (requests.RequestException, VercelOidcTokenError, KeyError):
        # a blob that is already gone is fine, but a missing or bad token (the KeyError is an
        # unset BLOB_STORE_ID) or a suspended store also lands here and would otherwise leak a blob per replacement with nothing said
        logger.warning("could not delete the replaced blob %s", url, exc_info=True)


def doomed(session: OrmSession) -> tuple[list[str], list[str]]:
    """The replay keys and the picture URLs of ours that the rows marked for deletion carry,
    themselves or through a cascade."""
    keys: list[str] = []
    urls: list[str] = []
    replays = select(col(DBSeriesReplay.key)).join(
        Series, col(Series.id) == col(DBSeriesReplay.series_id)
    )
    matches = replays.join(Match, col(Match.id) == col(Series.match_id))
    for row in session.deleted:
        match row:
            case Series():
                keys += session.scalars(replays.where(col(Series.id) == row.id))
            case Match():
                keys += session.scalars(replays.where(col(Series.match_id) == row.id))
            case Season():
                keys += session.scalars(matches.where(col(Match.season_id) == row.id))
            case User():
                keys += session.scalars(
                    replays.where(
                        or_(
                            col(Series.player1_id) == row.id,
                            col(Series.player2_id) == row.id,
                        )
                    )
                )
            case Team():
                keys += session.scalars(
                    matches.where(
                        or_(
                            col(Match.team1_id) == row.id, col(Match.team2_id) == row.id
                        )
                    )
                )
                urls += filter(None, [row.icon_url])
            case Map():
                urls += filter(None, [row.image])
    return keys, [url for url in urls if ours(url)]


@event.listens_for(Session, "before_flush")
def _collect(session: OrmSession, *_: object) -> None:
    keys, urls = doomed(session)
    session.info.setdefault("doomed_keys", []).extend(keys)
    session.info.setdefault("doomed_blobs", []).extend(urls)


@event.listens_for(Session, "after_commit")
def _drop(session: OrmSession) -> None:
    for key in session.info.pop("doomed_keys", []):
        r2.delete(key)
    for url in session.info.pop("doomed_blobs", []):
        delete_blob(url)


@event.listens_for(Session, "after_rollback")
def _forget(session: OrmSession) -> None:
    session.info.pop("doomed_keys", None)
    session.info.pop("doomed_blobs", None)


def demo() -> None:
    """The pathname and the content type follow the bytes, not the file name they arrived under."""
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 8
    jpeg = b"\xff\xd8\xff\xe0" + b"0" * 8
    assert icon_type(png) == "image/png"
    assert icon_type(jpeg) == "image/jpeg"
    assert EXTENSION[icon_type(png)] == "png"
    assert EXTENSION[icon_type(jpeg)] == "jpg"
    assert ours("https://abc.public.blob.vercel-storage.com/maps/8-x.png")
    assert not ours("https://d3upx5peno0o6w.cloudfront.net/echo.png")
    print("ok")


if __name__ == "__main__":
    demo()
