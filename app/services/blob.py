"""Team logos in Vercel Blob.

The SDK is imported inside each call, not at module scope: it carries its own httpx and a dozen
other packages, and only the upload route ever needs them. Reads never come here at all, because a
public blob is fetched by the browser straight from the store.

`BLOB_READ_WRITE_TOKEN` comes from the store connected to the Vercel project.
"""

from app.core.exceptions import BadRequestError

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_ICON_BYTES = 2 * 1024 * 1024
# the logo never changes under its own URL, because every upload gets a new random suffix
ICON_CACHE_SECONDS = 31_536_000


def check_icon(data: bytes) -> None:
    """A logo becomes a public URL, so it is checked before it is stored, not after."""
    if not data:
        raise BadRequestError("No image provided")
    if len(data) > MAX_ICON_BYTES:
        raise BadRequestError(f"Image is larger than {MAX_ICON_BYTES // 1024} KB")
    if not data.startswith(PNG_MAGIC):
        raise BadRequestError("Image must be a PNG")


def put_icon(team_id: int, data: bytes) -> str:
    """Store the logo and answer its public URL."""
    from vercel import blob

    result = blob.put(
        f"teams/{team_id}.png",
        data,
        access="public",
        content_type="image/png",
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
        pass
