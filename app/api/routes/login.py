import os
from typing import Any

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from app.api.deps import RequireRefresh
from app.core.exceptions import ApiError
from app.core.security import create_access_token, create_refresh_token
from app.models.login import LoginRequest

router = APIRouter(tags=["Authentication"])


@router.get("/")
def index() -> RedirectResponse:
    """Send the browser to the API documentation."""
    return RedirectResponse("/docs", status_code=302)


@router.post("/login")
def login(data: LoginRequest) -> dict[str, str]:
    """Exchange the admin token for an access token and a refresh token."""
    token_time = int(os.getenv("TOKEN_TIME", "15"))
    refresh_token_time = int(os.getenv("REFRESH_TOKEN_TIME", "300"))
    if data.token != os.getenv("ADMIN_TOKEN"):
        raise ApiError(401, {"error": "Bad admin token"})
    return {
        "access_token": create_access_token("admin", token_time),
        "refresh_token": create_refresh_token("admin", refresh_token_time),
    }


@router.post("/refresh")
def refresh(identity: RequireRefresh) -> dict[str, Any]:
    """Exchange a refresh token for a new access token."""
    token_time = int(os.getenv("TOKEN_TIME", "15"))
    new_access_token = create_access_token(identity, token_time)
    return {"access_token": new_access_token}
