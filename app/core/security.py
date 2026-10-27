"""The JWTs the backend signs: the admin token's, a member's Discord session, and the short-lived ones."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

# A member's session: the Discord login mints it, and it names the Discord account
SESSION_KIND = "discord"
# shortcut: no refresh or revocation, a session lives this long; add a sessions table if one must end early
SESSION_MINUTES = 30 * 24 * 60


def create_access_token(
    identity: str,
    minutes: int,
    kind: str = "access",
    extra: dict[str, Any] | None = None,
) -> str:
    """A signed token of one `kind`: `access` for the admin token, SESSION_KIND
    for a member's Discord login, `dev` for the local dev login. The OAuth flows
    sign their state with a kind of their own. `extra` adds claims of its own."""
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
