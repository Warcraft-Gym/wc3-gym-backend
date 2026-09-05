"""Game replays, in a Cloudflare R2 bucket, through its S3 API.

Every call is a presigned URL, signed here with the standard library (AWS Signature Version 4).
The browser uploads straight to the bucket with one, so no file passes through a Vercel function
and its 4.5 MB request cap. A download link is signed per read and lives `DOWNLOAD_SECONDS`, the
longest R2 allows. A tab left open longer gets a 403 from R2 and the reader refreshes the page.

Env: `CLOUDFLARE_R2_BUCKET`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_ACCESS_KEY_ID` and
`CLOUDFLARE_SECRET_ACCESS_KEY`, from the R2 API token scoped to that bucket. Production uses
`gnl-replays`; the preview and development targets use `gnl-replays-staging` with its own token.
A key also starts with `VERCEL_ENV`, so two builds on one bucket never share a file.
"""

import hashlib
import hmac
import logging
import os
from datetime import UTC, datetime
from urllib.parse import quote, urlencode

import requests

logger = logging.getLogger(__name__)

DOWNLOAD_SECONDS = 7 * 24 * 3600
UPLOAD_SECONDS = 600
ALGORITHM = "AWS4-HMAC-SHA256"


def key(series_id: int, game_no: int) -> str:
    """Where one game's replay lives, such as `production/replays/12/game1.w3g`."""
    return f"{os.getenv('VERCEL_ENV', 'development')}/replays/{series_id}/game{game_no}.w3g"


def presign(
    method: str,
    host: str,
    path: str,
    seconds: int,
    *,
    access_key: str,
    secret_key: str,
    region: str = "auto",
    now: datetime | None = None,
) -> str:
    """A URL that performs `method` on `path` at `host` for `seconds`, carrying the query
    signature R2 checks. No network call."""
    now = now or datetime.now(UTC)
    stamp, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    scope = f"{day}/{region}/s3/aws4_request"
    # in name order, as the signature requires
    query = urlencode(
        {
            "X-Amz-Algorithm": ALGORITHM,
            "X-Amz-Credential": f"{access_key}/{scope}",
            "X-Amz-Date": stamp,
            "X-Amz-Expires": str(seconds),
            "X-Amz-SignedHeaders": "host",
        }
    )
    canonical = "\n".join(
        [method, path, query, f"host:{host}\n", "host", "UNSIGNED-PAYLOAD"]
    )
    to_sign = "\n".join(
        [ALGORITHM, stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()]
    )
    signing_key = f"AWS4{secret_key}".encode()
    for part in (day, region, "s3", "aws4_request"):
        signing_key = hmac.new(signing_key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(signing_key, to_sign.encode(), hashlib.sha256).hexdigest()
    return f"https://{host}{path}?{query}&X-Amz-Signature={signature}"


def _signed(method: str, key: str, seconds: int) -> str:
    account = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    return presign(
        method,
        f"{account}.r2.cloudflarestorage.com",
        f"/{os.environ['CLOUDFLARE_R2_BUCKET']}/{quote(key)}",
        seconds,
        access_key=os.environ["CLOUDFLARE_ACCESS_KEY_ID"],
        secret_key=os.environ["CLOUDFLARE_SECRET_ACCESS_KEY"],
    )


def upload_url(key: str) -> str:
    """A link the browser PUTs one file to, for the next ten minutes, over whatever was there."""
    return _signed("PUT", key, UPLOAD_SECONDS)


def peek(key: str) -> tuple[bytes, int] | None:
    """The first bytes of the stored file and its size, or None when nothing is stored."""
    resp = requests.get(
        _signed("GET", key, 60), headers={"Range": "bytes=0-27"}, timeout=30
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    size = (
        resp.headers.get("Content-Range", "").rpartition("/")[2]
        or resp.headers["Content-Length"]
    )
    return resp.content[:28], int(size)


def fetch(key: str) -> bytes:
    """The whole stored file, for the Discord post."""
    resp = requests.get(_signed("GET", key, 60), timeout=30)
    resp.raise_for_status()
    return resp.content


def delete(key: str) -> None:
    """Drop the file under this key. A key with no file is not an error, and a store that refuses
    is logged: the row is already gone, and a delete must not fail on the file."""
    try:
        requests.delete(
            _signed("DELETE", key, UPLOAD_SECONDS), timeout=30
        ).raise_for_status()
    except requests.RequestException:
        logger.warning("could not delete the replay %s", key, exc_info=True)


def download_url(key: str) -> str:
    """A link that downloads the file for the next seven days."""
    return _signed("GET", key, DOWNLOAD_SECONDS)


def demo() -> None:
    """The signer reproduces the presigned GET from the AWS Signature Version 4 examples."""
    url = presign(
        "GET",
        "examplebucket.s3.amazonaws.com",
        "/test.txt",
        86400,
        access_key="AKIAIOSFODNN7EXAMPLE",
        secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        region="us-east-1",
        now=datetime(2013, 5, 24, tzinfo=UTC),
    )
    assert url.endswith(
        "aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"
    ), url
    print("ok")


if __name__ == "__main__":
    demo()
