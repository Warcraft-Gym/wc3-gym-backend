from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Self

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.enums import Race
from app.models.season import SeasonPublic
from app.models.types import EnumValue, NoneToList, NumToStr, SuggestRace
from app.models.user_team_season import UserTeamSeasonStatsPublic
from app.models.w3c_stats import W3CStats, W3CStatsPublic

if TYPE_CHECKING:
    from app.models.player_career_stats import PlayerCareerStats
    from app.models.relationships import DBFantasyTeamPlayer, DBUserSeasonSignup
    from app.models.user_team_season import DBUserTeamSeason


class UserBase(SQLModel):
    # The xlsx import sends numeric cells, and discordId numeric snowflakes
    name: Annotated[str, NumToStr] = Field(max_length=50)
    battleTag: Annotated[str, NumToStr] = Field(max_length=50)
    discordTag: Annotated[str, NumToStr] = Field(max_length=50)
    discordId: Annotated[str, NumToStr] = Field(max_length=50)
    mmr: int | None = None
    country: Annotated[str | None, NumToStr] = Field(default=None, max_length=2)
    fantasy_tier: int | None = None


class User(UserBase, DBModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    race: Race
    # When the app last asked w3champions about this player, null when never
    w3c_synced_at: datetime | None = None
    team_seasons: list["DBUserTeamSeason"] = Relationship(
        back_populates="user", sa_relationship_kwargs={"cascade": "all, delete"}
    )
    w3c_stats: list[W3CStats] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    fantasy_teams: list["DBFantasyTeamPlayer"] = Relationship(
        back_populates="users",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    signup_seasons: list["DBUserSeasonSignup"] = Relationship(
        back_populates="user", sa_relationship_kwargs={"cascade": "all, delete"}
    )
    career_stats: list["PlayerCareerStats"] = Relationship(back_populates="user")


class UserCreate(UserBase):
    race: Annotated[Race, SuggestRace]


class UserUpdate(SQLModel):
    name: Annotated[str | None, NumToStr] = None
    battleTag: Annotated[str | None, NumToStr] = None
    discordTag: Annotated[str | None, NumToStr] = None
    discordId: Annotated[str | None, NumToStr] = None
    race: Annotated[Race | None, SuggestRace] = None
    mmr: int | None = None
    country: Annotated[str | None, NumToStr] = None
    fantasy_tier: int | None = None


class UserReduced(UserBase):
    """The scalar fields of a user, without the per-season collections."""

    id: int | None = None
    # A user reached through another object may hold only some of these
    name: Annotated[str | None, NumToStr] = None
    battleTag: Annotated[str | None, NumToStr] = None
    discordTag: Annotated[str | None, NumToStr] = None
    discordId: Annotated[str | None, NumToStr] = None
    race: Annotated[str | None, EnumValue] = None
    w3c_synced_at: datetime | None = None

    @classmethod
    def from_user_reduced(cls, user: User | None) -> Self | None:
        """The scalar fields of the user. A subclass keeps its collections empty."""
        if not user:
            return None

        return cls(
            id=user.id,
            name=user.name,
            battleTag=user.battleTag,
            discordTag=user.discordTag,
            discordId=user.discordId,
            race=user.race,
            mmr=user.mmr,
            country=user.country,
            fantasy_tier=user.fantasy_tier,
            w3c_synced_at=user.w3c_synced_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class UserListPublic(UserReduced):
    """The user of a list answer: the scalars, the w3c stats and the signups."""

    w3c_stats: Annotated[list[W3CStatsPublic], NoneToList] = []
    signup_seasons: Annotated[list[SeasonPublic], NoneToList] = []

    @classmethod
    def from_user(cls, user: User | None) -> Self | None:
        if not user:
            return None

        row = cls.from_user_reduced(user)
        row.w3c_stats = [
            W3CStatsPublic.model_validate(stat) for stat in (user.w3c_stats or [])
        ]
        row.signup_seasons = [
            SeasonPublic.from_season_reduced(signup.season)
            for signup in (user.signup_seasons or [])
        ]
        return row


class UserPublic(UserListPublic):
    gnl_stats: Annotated[list[UserTeamSeasonStatsPublic], NoneToList] = []

    @classmethod
    def from_user(cls, user: User | None) -> Self | None:
        row = super().from_user(user)
        if not row:
            return None

        row.gnl_stats = [
            UserTeamSeasonStatsPublic.from_user_team_season(stat)
            for stat in (user.team_seasons or [])
        ]
        return row
