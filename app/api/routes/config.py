import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Body, Depends

from app.api.deps import SettingsServiceDep, require_admin
from app.core.exceptions import BadRequestError
from app.models.discord_role_binding import (
    DiscordRoleBindingCreate,
    DiscordRoleBindingPublic,
    DiscordRoleBindingUpdate,
    DiscordRoleReport,
)
from app.models.responses import Message
from app.models.settings import (
    GeneratedNightbotToken,
    NightbotToken,
    SettingsList,
    SettingsPublic,
    SettingsUpdated,
    SettingUpdated,
    W3CConfig,
)
from app.services import discord_roles
from app.services.w3c import W3CService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"])


@router.get("/config/settings")
def get_settings(service: SettingsServiceDep) -> SettingsList:
    """Retrieve all configuration settings from database."""
    return SettingsList(settings=service.get_all_settings())


@router.get("/config/w3c")
def get_w3c_config(service: SettingsServiceDep) -> W3CConfig:
    """The w3champions base URL and season in use, so the config page can show them."""
    w3c = W3CService(settings_app_service=service)
    try:
        current_season = w3c.current_season()
    except Exception as e:  # the page shows the URL even when w3champions is down
        logger.debug(f"w3champions gave no season: {e!s}")
        current_season = None
    return W3CConfig(w3c_url=w3c.base_url(), current_season=current_season)


@router.get("/config/settings/{key}")
def get_setting(key: str, service: SettingsServiceDep) -> SettingsPublic:
    """Retrieve a specific setting by key."""
    # get_by_key raises NotFoundError for an unknown key.
    return service.get_by_key(key)


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
    # get_setting raises NotFoundError, which answers 404
    setting = service.get_setting("KOTH_NIGHTBOT_TOKEN")
    return NightbotToken(token=setting.get("value"), exists=True)


@router.get("/config/discord-role-bindings", dependencies=[Depends(require_admin)])
def get_discord_role_bindings() -> list[DiscordRoleBindingPublic]:
    """Every Discord role the app owns, and what earns it."""
    return discord_roles.bindings()


@router.post(
    "/config/discord-role-bindings",
    status_code=201,
    dependencies=[Depends(require_admin)],
)
def add_discord_role_binding(
    data: DiscordRoleBindingCreate,
) -> DiscordRoleBindingPublic:
    """Bind a Discord role to a captain seat, a team, a fantasy team or a season."""
    return discord_roles.add_binding(data)


@router.put(
    "/config/discord-role-bindings/{binding_id}",
    dependencies=[Depends(require_admin)],
)
def update_discord_role_binding(
    binding_id: int, data: DiscordRoleBindingUpdate
) -> DiscordRoleBindingPublic:
    """Update one binding."""
    return discord_roles.update_binding(binding_id, data)


@router.delete(
    "/config/discord-role-bindings/{binding_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
def delete_discord_role_binding(binding_id: int) -> None:
    """Unbind a role. The guild keeps it; sync stops touching it."""
    discord_roles.delete_binding(binding_id)


@router.get("/config/discord-roles", dependencies=[Depends(require_admin)])
def get_discord_role_report() -> list[DiscordRoleReport]:
    """Every account whose guild roles differ from what the database says."""
    return discord_roles.report()


@router.post("/config/discord-roles/sync", dependencies=[Depends(require_admin)])
def sync_discord_roles(
    data: Annotated[dict | None, Body()] = None,
) -> list[DiscordRoleReport]:
    """Apply the difference. Without user_ids, every account the report flags."""
    return discord_roles.sync((data or {}).get("user_ids"))
