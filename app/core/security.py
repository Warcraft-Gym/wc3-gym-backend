"""Admin tokens, and the cleaning of untrusted input."""

import os
import re
import unicodedata
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt


def create_access_token(identity: str, minutes: int) -> str:
    """The admin token's access token; a player's session belongs to Clerk."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": identity,
            "type": "access",
            "jti": str(uuid.uuid4()),
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=minutes),
        },
        os.environ["JWT_SECRET_KEY"],
        algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
    )


def decode_token(token: str) -> dict[str, Any]:
    """Validate signature and expiry; raises jwt.InvalidTokenError."""
    return jwt.decode(
        token,
        os.environ["JWT_SECRET_KEY"],
        algorithms=[os.getenv("JWT_ALGORITHM", "HS256")],
        # A token minted this second must not read as from the future
        leeway=5,
    )


# secure_filename is copied from Werkzeug 3.x, BSD-3-Clause
# https://github.com/pallets/werkzeug

_filename_ascii_strip_re = re.compile(r"[^A-Za-z0-9_.-]")


def secure_filename(filename: str) -> str:
    """Return a safe version of an untrusted filename: ASCII only, no path
    separators, no leading dots or underscores."""
    filename = unicodedata.normalize("NFKD", filename)
    filename = filename.encode("ascii", "ignore").decode("ascii")

    for sep in os.sep, os.path.altsep:
        if sep:
            filename = filename.replace(sep, " ")
    filename = str(_filename_ascii_strip_re.sub("", "_".join(filename.split()))).strip(
        "._"
    )

    return filename
