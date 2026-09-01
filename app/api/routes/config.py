import logging
import secrets

from fastapi import APIRouter, Depends

from app.api.deps import RequireAdmin, SettingsServiceDep, require_admin
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.admin_grant import AdminGrantCreate, AdminPublic
from app.models.discord_role_binding import (
    DiscordRoleBindingCreate,
    DiscordRoleBindingPublic,
    DiscordRoleBindingUpdate,
    DiscordRoleReport,
    DiscordRoleSyncWrite,
)
from app.models.settings import (
    GeneratedNightbotToken,
    Message,
    NightbotToken,
    SettingsList,
    SettingsPublic,
    SettingsUpdated,
    SettingsWrite,
    SettingUpdated,
    SettingWrite,
    W3CConfig,
)
from app.services import admins, discord, discord_roles
from app.services.w3c import W3CService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"])

# Secrets never leave through the open settings reads; admins use the dedicated routes
SECRET_SETTINGS = frozenset({"KOTH_NIGHTBOT_TOKEN"})


@router.get("/config/settings")
def get_settings(service: SettingsServiceDep) -> SettingsList:
    """Retrieve all configuration settings from database."""
    return SettingsList(
        settings=[s for s in service.get_all() if s.key not in SECRET_SETTINGS]
    )


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
    if key in SECRET_SETTINGS:
        raise NotFoundError(f"Setting with key '{key}' not found")
    # get_by_key raises NotFoundError for an unknown key.
    return service.get_by_key(key)


@router.put("/config/settings", dependencies=[Depends(require_admin)])
def update_settings(
    data: SettingsWrite, service: SettingsServiceDep
) -> SettingsUpdated:
    """Update one or more configuration settings."""
    settings = data.settings

    if not settings:
        raise BadRequestError("No settings provided")

    updated = service.update_settings(settings)
    return SettingsUpdated(message="Settings updated successfully", updated=updated)


@router.put("/config/settings/{key}", dependencies=[Depends(require_admin)])
def update_setting(
    key: str, data: SettingWrite, service: SettingsServiceDep
) -> SettingUpdated:
    """Update a specific setting by key."""
    value = data.value
    description = data.description

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
    # get_by_key raises NotFoundError, which answers 404
    setting = service.get_by_key("KOTH_NIGHTBOT_TOKEN")
    return NightbotToken(token=setting.value, exists=True)


@router.get("/config/admins", dependencies=[Depends(require_admin)])
def get_admins() -> list[AdminPublic]:
    """Every account that administers the site, from the environment and the table."""
    return admins.admins()


@router.post("/config/admins", status_code=201)
def add_admin(data: AdminGrantCreate, granted_by: RequireAdmin) -> AdminPublic:
    """Make that Discord account an admin, and mirror the grant to the guild."""
    return admins.grant(data.discord_id, granted_by, data.name)


@router.delete("/config/admins/{discord_id}", status_code=204)
def delete_admin(discord_id: str, by: RequireAdmin) -> None:
    """Take a grant back. The environment ids and the caller's own grant stay."""
    admins.revoke(discord_id, by)


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


@router.get("/config/discord-guild-roles", dependencies=[Depends(require_admin)])
def get_discord_guild_roles() -> dict[str, str]:
    """The name of every guild role by id, for the pages that show role ids."""
    return discord.guild_roles()


@router.post("/config/discord-roles/sync", dependencies=[Depends(require_admin)])
def sync_discord_roles(
    data: DiscordRoleSyncWrite | None = None,
) -> list[DiscordRoleReport]:
    """Apply the difference. Without user_ids, every account the report flags."""
    return discord_roles.sync(data.user_ids if data else None)
