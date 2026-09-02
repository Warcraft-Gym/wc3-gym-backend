"""Team logos in Vercel Blob.

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
# the logo never changes under its own URL, because every upload gets a new random suffix
ICON_CACHE_SECONDS = 31_536_000


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


def stored_type(data: bytes) -> str:
    """The media type of bytes already in the database, which predate any check on the way in."""
    for magic, media_type in MAGIC.items():
        if data.startswith(magic):
            return media_type
    return "application/octet-stream"


def put_icon(team_id: int, data: bytes) -> str:
    """Store the logo and answer its public URL."""
    from vercel import blob

    media_type = icon_type(data)
    result = blob.put(
        f"teams/{team_id}.{EXTENSION[media_type]}",
        data,
        access="public",
        content_type=media_type,
        # a new URL every time, so no browser holds a replaced logo for the cache year
        add_random_suffix=True,
        cache_control_max_age=ICON_CACHE_SECONDS,
    )
    return result.url


def delete_icon(url: str) -> None:
    """Drop a replaced logo. Deletes are free, and a missing blob is not an error worth raising."""
    from vercel import blob
    from vercel.blob import BlobError

    try:
        blob.delete(url)
    except BlobError:
        # a blob that is already gone is fine, but a bad token or a suspended store also lands
        # here and would otherwise leak a logo per replacement with nothing said
        logger.warning("could not delete the replaced logo %s", url, exc_info=True)


def demo() -> None:
    """The pathname and the content type follow the bytes, not the file name they arrived under."""
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 8
    jpeg = b"\xff\xd8\xff\xe0" + b"0" * 8
    assert icon_type(png) == "image/png"
    assert icon_type(jpeg) == "image/jpeg"
    assert EXTENSION[icon_type(png)] == "png"
    assert EXTENSION[icon_type(jpeg)] == "jpg"
    print("ok")


if __name__ == "__main__":
    demo()
