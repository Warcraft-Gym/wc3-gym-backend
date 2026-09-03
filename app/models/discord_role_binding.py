"""Which Discord role a fact in the database earns.

The app owns every bound role: app.services.discord_roles derives who earns
which one and pushes the difference to the guild. A role no binding names is
nobody's business but the guild's, and sync never touches it — nor any admin
binding, whose role stays hand-managed in the guild.

A binding is synced only when its synced flag is set. Its scope says which
seasons it reads: the current one, the season it names, or every season. A
champion binding is scoped to one season, and the roster of the team that
tops its standings earns it.

A hidden role is one an admin marked as none of the app's business, so it
can never be bound.
"""

from typing import Annotated

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.enums import RoleKind, RoleScope
from app.models.types import NumToStr


class DiscordRoleBindingBase(SQLModel):
    kind: RoleKind
    scope: RoleScope = Field(default=RoleScope.current)
    # Read only by a binding scoped to a season
    season_id: int | None = Field(
        default=None, index=True, foreign_key="seasons.id", ondelete="CASCADE"
    )
    team_id: int | None = Field(
        default=None, index=True, foreign_key="teams.id", ondelete="CASCADE"
    )
    # The xlsx import sends numeric cells, and a role id is a snowflake
    discord_role: Annotated[str, NumToStr] = Field(max_length=50)
    synced: bool = Field(default=False)


class DiscordRoleBinding(DiscordRoleBindingBase, DBModel, table=True):
    __tablename__ = "discord_role_binding"
    # One role belongs to one binding, the way a club was its team role
    __table_args__ = (
        Index("uq_discord_role_binding_discord_role", "discord_role", unique=True),
    )

    id: int | None = Field(default=None, primary_key=True)


class DiscordRoleBindingCreate(DiscordRoleBindingBase):
    pass


class DiscordRoleBindingUpdate(SQLModel):
    kind: RoleKind | None = None
    scope: RoleScope | None = None
    season_id: int | None = None
    team_id: int | None = None
    discord_role: Annotated[str | None, NumToStr] = None
    synced: bool | None = None


class DiscordRoleBindingPublic(DiscordRoleBindingBase):
    id: int


class DiscordRoleHiddenWrite(SQLModel):
    """A guild role an admin hid, which the app must never bind or sync."""

    # The role page sends the id as a number, and a role id is a snowflake
    discord_role: Annotated[str, NumToStr] = Field(max_length=50, primary_key=True)


class DiscordRoleHidden(DiscordRoleHiddenWrite, DBModel, table=True):
    __tablename__ = "discord_role_hidden"


class DiscordRoleSyncWrite(SQLModel):
    """Whom to sync. Without user_ids every flagged account, without role_ids every bound role."""

    user_ids: list[int] | None = None
    role_ids: list[str] | None = None


class GuildRole(SQLModel):
    """One role of the guild, as the Discord role page lists it."""

    id: str
    name: str
    color: str | None = None
    position: int
    members: int
    manageable: bool
    # Set by discord_roles.guild_roles from the roles an admin hid
    hidden: bool = False


class RoleGroup(SQLModel):
    """One group of accounts a binding can name, and how many earn it now."""

    kind: RoleKind
    scope: RoleScope = RoleScope.current
    season_id: int | None = None
    team_id: int | None = None
    label: str
    # Filled by discord_roles.role_groups once the earning rules have run
    count: int = 0


class DiscordRoleReport(SQLModel):
    """One account's diff: bound roles it earns and lacks, and holds and does not."""

    user_id: int
    discord_id: str
    name: str
    missing: list[str] = []
    extra: list[str] = []
