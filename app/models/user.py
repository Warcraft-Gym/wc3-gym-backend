from typing import TYPE_CHECKING, Annotated

from sqlalchemy.orm import Session
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.enums import Race
from app.models.relationships import DBUserTeamSeason
from app.models.season import SeasonPublic
from app.models.types import NoneToList, NumToStr
from app.models.user_team_season_stats import UserTeamSeasonStatsPublic
from app.models.w3c_stats import W3CStats, W3CStatsPublic

if TYPE_CHECKING:
    from app.models.player_career_stats import PlayerCareerStats
    from app.models.relationships import DBFantasyTeamPlayer, DBUserSeasonSignup


class UserBase(SQLModel):
    # These fields receive raw numeric cells from the xlsx import, and
    # discordId also receives numeric snowflakes from JSON bodies.
    name: Annotated[str, NumToStr] = Field(max_length=50)
    battleTag: Annotated[str, NumToStr] = Field(max_length=50)
    discordTag: Annotated[str, NumToStr] = Field(max_length=50)
    discordId: Annotated[str, NumToStr] = Field(max_length=50)
    mmr: int | None = None
    country: Annotated[str | None, NumToStr] = Field(default=None, max_length=2)
    fantasy_tier: int | None = None


class User(UserBase, DBModel, table=True):
    __tablename__ = "users"
    __table_args__ = {"mysql_charset": "utf8mb4"}

    id: int | None = Field(default=None, primary_key=True)
    race: Race
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

    @classmethod
    def updateUserTeamSeasonStats(cls, session: Session, season_stats):
        from app.models.season import Season
        from app.models.team import Team

        team = session.get(Team, season_stats.team_id)
        if not team:
            raise Exception(f"Team not found by id: {season_stats.team_id}")
        season = session.get(Season, season_stats.season_id)
        if not season:
            raise Exception(f"Season not found by id: {season_stats.season_id}")
        user = session.get(cls, season_stats.user_id)
        if not user:
            raise Exception(f"User not found by id: {season_stats.user_id}")
        uts_obj = session.get(
            DBUserTeamSeason,
            {"team_id": team.id, "season_id": season.id, "user_id": user.id},
        )
        if uts_obj is None:
            uts_obj = DBUserTeamSeason(user=user, season=season, team=team)
            session.add(uts_obj)
        uts_obj.games = season_stats.games
        uts_obj.wins = season_stats.wins
        uts_obj.losses = season_stats.losses
        uts_obj.matchup_history = season_stats.matchup_history
        session.flush()
        return uts_obj


class UserCreate(UserBase):
    # A Race member when the value comes from a sync, a plain string when
    # it comes from request JSON. Services compare members, so the value
    # is not coerced.
    race: Race | str


class UserUpdate(SQLModel):
    name: Annotated[str | None, NumToStr] = None
    battleTag: Annotated[str | None, NumToStr] = None
    discordTag: Annotated[str | None, NumToStr] = None
    discordId: Annotated[str | None, NumToStr] = None
    race: Race | str | None = None
    mmr: int | None = None
    country: Annotated[str | None, NumToStr] = None
    fantasy_tier: int | None = None


class UserPublic(UserBase):
    id: int | None = None
    # A user reached through another object can be built from a row that
    # holds only some of these, so the response keeps them all optional.
    name: Annotated[str | None, NumToStr] = None
    battleTag: Annotated[str | None, NumToStr] = None
    discordTag: Annotated[str | None, NumToStr] = None
    discordId: Annotated[str | None, NumToStr] = None
    race: Race | str | None = None
    w3c_stats: Annotated[list[W3CStatsPublic], NoneToList] = []
    gnl_stats: Annotated[list[UserTeamSeasonStatsPublic], NoneToList] = []
    signup_seasons: Annotated[list[SeasonPublic], NoneToList] = []

    @classmethod
    def from_user(cls, user):
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
            w3c_stats=[
                W3CStatsPublic.model_validate(stat) for stat in (user.w3c_stats or [])
            ],
            gnl_stats=[
                UserTeamSeasonStatsPublic.from_user_team_season(stat)
                for stat in (user.team_seasons or [])
            ],
            fantasy_tier=user.fantasy_tier,
            signup_seasons=[
                SeasonPublic.from_season_reduced(signup.season)
                for signup in (user.signup_seasons or [])
            ],
        )

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")
