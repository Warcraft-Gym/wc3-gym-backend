import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Body, Depends

from app.api.deps import SettingsServiceDep, require_admin
from app.exceptions import BadRequestError
from app.models.responses import Message
from app.models.settings import (
    GeneratedNightbotToken,
    NightbotToken,
    SettingsList,
    SettingsPublic,
    SettingsUpdated,
    SettingUpdated,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"])


@router.get("/config/settings")
def get_settings(service: SettingsServiceDep) -> SettingsList:
    """Retrieve all configuration settings from database."""
    return SettingsList(settings=service.get_all_settings())


@router.get("/config/settings/{key}")
def get_setting(key: str, service: SettingsServiceDep) -> SettingsPublic:
    """Retrieve a specific setting by key."""
    # get_setting raises NotFoundError for an unknown key.
    return service.get_setting(key)


@router.put("/config/settings", dependencies=[Depends(require_admin)])
def update_settings(
    data: Annotated[dict, Body()], service: SettingsServiceDep
) -> SettingsUpdated:
    """Update one or more configuration settings."""
    settings = data.get("settings", {})

    if not settings:
        raise BadRequestError("No settings provided")

    updated = service.update_settings(settings)
    return SettingsUpdated(message="Settings updated successfully", updated=updated)


@router.put("/config/settings/{key}", dependencies=[Depends(require_admin)])
def update_setting(
    key: str, data: Annotated[dict, Body()], service: SettingsServiceDep
) -> SettingUpdated:
    """Update a specific setting by key."""
    value = data.get("value")
    description = data.get("description")

    if value is None:
        raise BadRequestError("Value is required")

    setting = service.update_setting(key, value, description)
    return SettingUpdated(
        message=f"Setting '{key}' updated successfully", setting=setting
    )


@router.delete("/config/settings/{key}", dependencies=[Depends(require_admin)])
def delete_setting(key: str, service: SettingsServiceDep) -> Message:
    """Delete a specific setting by key."""
    service.delete_setting(key)
    return Message(message=f"Setting '{key}' deleted successfully")


@router.post("/config/koth/nightbot-token", dependencies=[Depends(require_admin)])
def generate_nightbot_token(service: SettingsServiceDep) -> GeneratedNightbotToken:
    """Generate a new secure token for KOTH Nightbot integration"""
    # Generate a secure random token (64 characters hex)
    new_token = secrets.token_hex(32)

    # Store in settings
    service.update_setting(
        "KOTH_NIGHTBOT_TOKEN",
        new_token,
        "Secure token for KOTH Nightbot command integration",
    )

    return GeneratedNightbotToken(
        token=new_token, message="KOTH Nightbot token generated successfully"
    )


@router.get("/config/koth/nightbot-token", dependencies=[Depends(require_admin)])
def get_nightbot_token(service: SettingsServiceDep) -> NightbotToken:
    """Get the current KOTH Nightbot token"""
    # get_setting raises NotFoundError for a missing token, so a missing
    # token answers 404.
    setting = service.get_setting("KOTH_NIGHTBOT_TOKEN")
    return NightbotToken(token=setting.get("value"), exists=True)
