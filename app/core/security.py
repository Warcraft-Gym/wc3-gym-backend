"""The admin token's JWT."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt


def create_access_token(
    identity: str,
    minutes: int,
    kind: str = "access",
    extra: dict[str, Any] | None = None,
) -> str:
    """The admin token's access token; a player's session belongs to Clerk.
    Another `kind` is no login: the Battle.net link signs its state with it,
    and the local dev login mints `dev`. `extra` adds claims of its own."""
    now = datetime.now(UTC)
    return jwt.encode(
        (extra or {})
        | {
            "sub": identity,
            "type": kind,
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


def is_admin(claims: dict[str, Any] | None) -> bool:
    """Whether the claims carry the admin role, or are the admin access token's."""
    return claims is not None and (
        claims.get("role") == "admin" or claims.get("sub") == "admin"
    )


def dev_login_enabled() -> bool:
    """Whether the local dev login answers: DEV_LOGIN=1 on a machine that is no deployment."""
    return os.getenv("DEV_LOGIN") == "1" and not os.getenv("VERCEL")
