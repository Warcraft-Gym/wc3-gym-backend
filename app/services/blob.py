"""The files the app owns, in Vercel Blob: team logos, map thumbnails and game replays.

The SDK is imported inside each call, not at module scope: it carries its own httpx and a dozen
other packages, and only the upload route ever needs them. Reads never come here at all, because a
public blob is fetched by the browser straight from the store.

`BLOB_READ_WRITE_TOKEN` comes from the store connected to the Vercel project.
"""

import logging

from app.core.exceptions import BadRequestError

logger = logging.getLogger(__name__)

# three of the ten logos in production are JPEGs that were stored and served as image/png;
# browsers sniff the bytes, so nobody noticed. Both are accepted, and each is served as what it is.
MAGIC = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg"}
EXTENSION = {"image/png": "png", "image/jpeg": "jpg"}
MAX_ICON_BYTES = 2 * 1024 * 1024
# a blob never changes under its own URL, because every upload gets a new random suffix
ICON_CACHE_SECONDS = 31_536_000
REPLAY_MAGIC = b"Warcraft III recorded game\x1a\x00"
# a game runs about 250 bytes a second, so this is a four-hour game; Vercel caps a request at 4.5 MB
MAX_REPLAY_BYTES = 4 * 1024 * 1024


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


def put_icon(name: str, data: bytes) -> str:
    """Store the picture under this name, such as `teams/4`, and answer its public URL."""
    from vercel import blob

    media_type = icon_type(data)
    result = blob.put(
        f"{name}.{EXTENSION[media_type]}",
        data,
        access="public",
        content_type=media_type,
        # a new URL every time, so no browser holds a replaced logo for the cache year
        add_random_suffix=True,
        cache_control_max_age=ICON_CACHE_SECONDS,
    )
    return result.url


def replay_check(data: bytes) -> None:
    """Refuse anything that is not a Warcraft III replay. It becomes a public URL, so this runs
    before it is stored, not after."""
    if not data.startswith(REPLAY_MAGIC):
        raise BadRequestError("Not a Warcraft III replay")
    if len(data) > MAX_REPLAY_BYTES:
        raise BadRequestError(f"Replay is larger than {MAX_REPLAY_BYTES // 1024} KB")


def put_replay(name: str, data: bytes) -> str:
    """Store the replay under this name, such as `replays/12/game1`, and answer its public URL."""
    from vercel import blob

    replay_check(data)
    result = blob.put(
        f"{name}.w3g",
        data,
        access="public",
        content_type="application/octet-stream",
        add_random_suffix=True,
        cache_control_max_age=ICON_CACHE_SECONDS,
    )
    return result.url


def ours(url: str) -> bool:
    """Whether we wrote this picture. A map picture can be the url warcraft3.info publishes it
    at, which is not ours to delete."""
    return ".public.blob.vercel-storage.com/" in url


def delete_blob(url: str) -> None:
    """Drop a replaced blob. Deletes are free, and a missing blob is not an error worth raising."""
    from vercel import blob
    from vercel.blob import BlobError

    try:
        blob.delete(url)
    except BlobError:
        # a blob that is already gone is fine, but a bad token or a suspended store also lands
        # here and would otherwise leak a blob per replacement with nothing said
        logger.warning("could not delete the replaced blob %s", url, exc_info=True)


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
    replay_check(REPLAY_MAGIC + b"\0" * 8)
    for bad in (b"", b"replay", REPLAY_MAGIC + b"\0" * (MAX_REPLAY_BYTES + 1)):
        try:
            replay_check(bad)
        except BadRequestError:
            continue
        raise AssertionError(f"{bad[:8]!r} was accepted")
    print("ok")


if __name__ == "__main__":
    demo()
