"""Which Discord role a fact in the database earns.

The app owns every bound role: app.services.discord_roles derives who earns
which one and pushes the difference to the guild. A role no binding names is
nobody's business but the guild's, and sync never touches it.

A null season means the binding holds in every season, a null team in every
team. A champion binding names both, and the roster of that team in that
season is who earns it.
"""

from typing import Annotated

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.enums import RoleKind
from app.models.types import NumToStr


class DiscordRoleBindingBase(SQLModel):
    kind: RoleKind
    season_id: int | None = Field(
        default=None, index=True, foreign_key="seasons.id", ondelete="CASCADE"
    )
    team_id: int | None = Field(
        default=None, index=True, foreign_key="teams.id", ondelete="CASCADE"
    )
    # The xlsx import sends numeric cells, and a role id is a snowflake
    discord_role: Annotated[str, NumToStr] = Field(max_length=50)


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
    season_id: int | None = None
    team_id: int | None = None
    discord_role: Annotated[str | None, NumToStr] = None


class DiscordRoleBindingPublic(DiscordRoleBindingBase):
    id: int


class DiscordRoleReport(SQLModel):
    """One account's diff: bound roles it earns and lacks, and holds and does not."""

    user_id: int
    discord_id: str
    name: str
    missing: list[str] = []
    extra: list[str] = []
