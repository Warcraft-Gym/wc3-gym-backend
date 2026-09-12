"""The admin token's JWT."""

import os
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
