from datetime import datetime
from typing import TYPE_CHECKING, Annotated, ClassVar, Self

from sqlalchemy import Index, select, text
from sqlalchemy.orm import column_property
from sqlalchemy.orm.attributes import instance_state
from sqlmodel import Field, Relationship, SQLModel, col

from app.models.base import DBModel, PublicModel, ident
from app.models.enums import Race
from app.models.season import SeasonPublic
from app.models.types import (
    EnumValue,
    KnownTimeZone,
    NoneToList,
    NumToStr,
    SuggestRace,
    TwitchChannel,
    UTCDateTime,
    YouTubeChannel,
)
from app.models.user_battle_tag import UserBattleTag, UserBattleTagPublic
from app.models.user_team_season import UserTeamSeasonStatsPublic
from app.models.w3c_stats import W3CStats, W3CStatsPublic

if TYPE_CHECKING:
    from app.models.player_career_stats import PlayerCareerStats
    from app.models.relationships import DBFantasyTeamPlayer, DBUserSeasonSignup
    from app.models.user_team_season import DBUserTeamSeason


class UserBase(SQLModel):
    name: str = Field(max_length=50)
    # Null for a person who never logged in
    discordTag: str | None = Field(max_length=50)
    discordId: str | None = Field(max_length=50)
    mmr: int | None = None
    # ISO 3166-1 alpha-2, or a UK nation as GB-SCT
    country: str | None = Field(default=None, max_length=6)
    # IANA name, as the browser reports it: America/New_York
    timezone: str | None = Field(default=None, max_length=64)
    # The player's own channels, as links; a video link is refused
    twitch_url: str | None = Field(default=None, max_length=200)
    youtube_url: str | None = Field(default=None, max_length=200)
    # The Discord avatar image the login last read, written by the app
    avatar_url: str | None = Field(default=None, max_length=300)


class User(UserBase, DBModel, table=True):
    __tablename__ = "users"
    # The fantasy importer matches a bettor by Discord tag, case blind. A Clerk
    # session matches a player by Discord id. Blank or null means unknown.
    __table_args__ = (
        Index(
            "uq_users_discord_tag",
            text('lower(trim("discordTag"))'),
            unique=True,
            sqlite_where=text("trim(\"discordTag\") <> ''"),
            postgresql_where=text("trim(\"discordTag\") <> ''"),
        ),
        Index(
            "uq_users_discord_id",
            text('trim("discordId")'),
            unique=True,
            sqlite_where=text("trim(\"discordId\") <> ''"),
            postgresql_where=text("trim(\"discordId\") <> ''"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    # The active tag's text, null with no tag; read-only, mapped below the class
    battleTag: ClassVar[str | None]
    race: Race
    # When the app last asked w3champions about this player, null when never
    w3c_synced_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    # When the app last asked w3champions for this player's ladder matches
    ladder_synced_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    # An admin banned this player; the entrant row warns and never refuses
    banned_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
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
    # Every tag the person played under, the active one first
    battle_tags: list[UserBattleTag] = Relationship(
        sa_relationship_kwargs={
            "cascade": "all, delete",
            "order_by": "(UserBattleTag.is_active.desc(), UserBattleTag.id)",
        }
    )


# One indexed lookup inside every users SELECT, so a list of users costs no extra statement
User.battleTag = column_property(
    select(col(UserBattleTag.tag))
    .where(col(UserBattleTag.user_id) == col(User.id), col(UserBattleTag.is_active))
    .correlate_except(UserBattleTag)
    .scalar_subquery()
)


class UserCreate(UserBase):
    # The xlsx import sends numeric cells, and discordId numeric snowflakes
    name: Annotated[str, NumToStr] = Field(max_length=50)
    battleTag: Annotated[str, NumToStr] = Field(max_length=50)
    discordTag: Annotated[str, NumToStr] = Field(max_length=50)
    discordId: Annotated[str, NumToStr] = Field(max_length=50)
    country: Annotated[str | None, NumToStr] = Field(default=None, max_length=6)
    timezone: Annotated[str | None, KnownTimeZone] = Field(default=None, max_length=64)
    twitch_url: Annotated[str | None, TwitchChannel] = Field(
        default=None, max_length=200
    )
    youtube_url: Annotated[str | None, YouTubeChannel] = Field(
        default=None, max_length=200
    )
    race: Annotated[Race, SuggestRace]


class UserUpdate(SQLModel):
    name: Annotated[str | None, NumToStr] = None
    battleTag: Annotated[str | None, NumToStr] = None
    discordTag: Annotated[str | None, NumToStr] = None
    discordId: Annotated[str | None, NumToStr] = None
    race: Annotated[Race | None, SuggestRace] = None
    mmr: int | None = None
    country: Annotated[str | None, NumToStr] = None
    timezone: Annotated[str | None, KnownTimeZone] = None
    twitch_url: Annotated[str | None, TwitchChannel] = None
    youtube_url: Annotated[str | None, YouTubeChannel] = None


class PublicSignupWrite(SQLModel):
    """The public signup form. The Discord identity comes from the session,
    never from here, and UserCreate is what rejects a bad profile."""

    name: Annotated[str | None, NumToStr] = None
    battleTag: Annotated[str | None, NumToStr] = None
    race: str | None = None
    mmr: int | None = None
    country: Annotated[str | None, NumToStr] = None
    timezone: str | None = None
    season_id: int | None = None


class ProfileUpdate(SQLModel):
    """The fields a member may change on their own profile."""

    name: Annotated[str | None, NumToStr] = None
    battleTag: Annotated[str | None, NumToStr] = None
    race: Annotated[Race | None, SuggestRace] = None
    country: Annotated[str | None, NumToStr] = None
    timezone: Annotated[str | None, KnownTimeZone] = None
    twitch_url: Annotated[str | None, TwitchChannel] = None
    youtube_url: Annotated[str | None, YouTubeChannel] = None


class UserReduced(UserBase, PublicModel):
    """The scalar fields of a user, without the per-season collections."""

    id: int
    # A user reached through another object may hold only some of these
    name: str | None = None
    battleTag: str | None = None
    discordTag: str | None = None
    discordId: str | None = None
    race: Annotated[str | None, EnumValue] = None
    w3c_synced_at: datetime | None = None
    ladder_synced_at: datetime | None = None

    @classmethod
    def from_user_reduced(cls, user: User) -> Self:
        """The scalar fields of the user. A subclass keeps its collections empty."""
        return cls(
            id=ident(user),
            name=user.name,
            battleTag=user.battleTag,
            discordTag=user.discordTag,
            discordId=user.discordId,
            race=user.race,
            mmr=user.mmr,
            country=user.country,
            timezone=user.timezone,
            twitch_url=user.twitch_url,
            youtube_url=user.youtube_url,
            avatar_url=user.avatar_url,
            w3c_synced_at=user.w3c_synced_at,
            ladder_synced_at=user.ladder_synced_at,
        )


class UserListPublic(UserReduced):
    """The user of a list answer: the scalars, the w3c stats and the signups."""

    w3c_stats: Annotated[list[W3CStatsPublic], NoneToList] = []
    signup_seasons: Annotated[list[SeasonPublic], NoneToList] = []
    # The race and tier of one signup, filled by the signups answer of a single season
    signup_race: Annotated[str | None, EnumValue] = None
    # The tag of that signup, null when it names none
    played_as: str | None = None
    fantasy_tier: int | None = None
    # Set by hand on the signup row; an unpinned tier derives from the MMR
    fantasy_tier_pinned: bool = False
    draft_position: int | None = None
    # An admin took the player out of the pick list of the season
    draft_excluded: bool = False
    # Every tag the person holds, the active one first; empty where the read
    # loads no tags
    tags: Annotated[list[UserBattleTagPublic], NoneToList] = []

    @classmethod
    def from_user(cls, user: User) -> Self:
        row = cls.from_user_reduced(user)
        row.w3c_stats = [
            W3CStatsPublic.model_validate(stat) for stat in (user.w3c_stats or [])
        ]
        row.signup_seasons = [
            SeasonPublic.from_season_reduced(
                signup.season, signup.race, signup.played_as
            )
            for signup in (user.signup_seasons or [])
        ]
        # A read that did not load the tags leaves them empty, never lazy loads
        if "battle_tags" not in instance_state(user).unloaded:
            row.tags = [UserBattleTagPublic.from_row(tag) for tag in user.battle_tags]
        return row


class TrophyPublic(SQLModel):
    """One thing a player won, drawn as a crowned team logo on his dashboard.

    Today the only trophy is the league championship of a finished season.
    A tournament win is the same row under another title.
    """

    title: str
    season_id: int | None = None
    # The season on its own, because the mark engraves it apart from the title
    season_name: str | None = None
    # The short name of the season's league; null when the event has no league
    league_short_name: str | None = None
    team_id: int | None = None
    team_name: str | None = None
    team_icon_url: str | None = None


class UserPublic(UserListPublic):
    gnl_stats: Annotated[list[UserTeamSeasonStatsPublic], NoneToList] = []
    # Derived by app.services.derived.fill_trophies; empty until it runs
    trophies: Annotated[list[TrophyPublic], NoneToList] = []

    @classmethod
    def from_user(cls, user: User) -> Self:
        row = super().from_user(user)
        row.gnl_stats = [
            UserTeamSeasonStatsPublic.from_user_team_season(stat)
            for stat in (user.team_seasons or [])
        ]
        return row
