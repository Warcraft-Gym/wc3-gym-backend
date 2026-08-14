import logging
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from app.api.deps import SettingsServiceDep, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"])


@router.get("/config/settings")
def get_settings(service: SettingsServiceDep) -> dict[str, Any]:
    """Retrieve all configuration settings from database."""
    settings = service.get_all_settings()
    return {"settings": settings}


@router.get("/config/settings/{key}")
def get_setting(key: str, service: SettingsServiceDep) -> JSONResponse:
    """Retrieve a specific setting by key."""
    setting = service.get_setting(key)
    if not setting:
        return JSONResponse({"error": f"Setting '{key}' not found"}, status_code=404)
    return JSONResponse(setting, status_code=200)


@router.put("/config/settings", dependencies=[Depends(require_admin)])
def update_settings(
    data: Annotated[dict, Body()], service: SettingsServiceDep
) -> JSONResponse:
    """Update one or more configuration settings."""
    settings = data.get("settings", {})

    if not settings:
        return JSONResponse({"error": "No settings provided"}, status_code=400)

    updated = service.update_settings(settings)

    return JSONResponse(
        {"message": "Settings updated successfully", "updated": updated},
        status_code=200,
    )


@router.put("/config/settings/{key}", dependencies=[Depends(require_admin)])
def update_setting(
    key: str, data: Annotated[dict, Body()], service: SettingsServiceDep
) -> JSONResponse:
    """Update a specific setting by key."""
    value = data.get("value")
    description = data.get("description")

    if value is None:
        return JSONResponse({"error": "Value is required"}, status_code=400)

    setting = service.update_setting(key, value, description)

    return JSONResponse(
        {"message": f"Setting '{key}' updated successfully", "setting": setting},
        status_code=200,
    )


@router.delete("/config/settings/{key}", dependencies=[Depends(require_admin)])
def delete_setting(key: str, service: SettingsServiceDep) -> JSONResponse:
    """Delete a specific setting by key."""
    service.delete_setting(key)
    return JSONResponse(
        {"message": f"Setting '{key}' deleted successfully"}, status_code=200
    )


@router.post("/config/koth/nightbot-token", dependencies=[Depends(require_admin)])
def generate_nightbot_token(service: SettingsServiceDep) -> dict[str, Any]:
    """Generate a new secure token for KOTH Nightbot integration"""
    # Generate a secure random token (64 characters hex)
    new_token = secrets.token_hex(32)

    # Store in settings
    service.update_setting(
        "KOTH_NIGHTBOT_TOKEN",
        new_token,
        "Secure token for KOTH Nightbot command integration",
    )

    return {
        "token": new_token,
        "message": "KOTH Nightbot token generated successfully",
    }


@router.get("/config/koth/nightbot-token", dependencies=[Depends(require_admin)])
def get_nightbot_token(service: SettingsServiceDep) -> dict[str, Any] | None:
    """Get the current KOTH Nightbot token"""
    setting = service.get_setting("KOTH_NIGHTBOT_TOKEN")

    if setting:
        return {"token": setting.get("value"), "exists": True}
    else:
        return {"token": None, "exists": False}
