"""Admin token minting and validation.

The tokens are compatible with the ones flask_jwt_extended issued before
the FastAPI port: HS256 (JWT_ALGORITHM) signed with JWT_SECRET_KEY, with
sub, type, jti, iat, nbf and exp claims. A token issued before the port
keeps working after it.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt


def _mint(identity: str, token_type: str, minutes: int) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": identity,
            "type": token_type,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=minutes),
        },
        os.getenv("JWT_SECRET_KEY"),
        algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
    )


def create_access_token(identity: str, minutes: int) -> str:
    return _mint(identity, "access", minutes)


def create_refresh_token(identity: str, minutes: int) -> str:
    return _mint(identity, "refresh", minutes)


def decode_token(token: str) -> dict[str, Any]:
    """Validate signature and expiry; raises jwt.InvalidTokenError."""
    return jwt.decode(
        token,
        os.getenv("JWT_SECRET_KEY"),
        algorithms=[os.getenv("JWT_ALGORITHM", "HS256")],
    )
