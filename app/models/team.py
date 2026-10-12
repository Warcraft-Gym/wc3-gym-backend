from typing import TYPE_CHECKING, Annotated, Self

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.season_info import SeasonInfoPublic
from app.models.team_summary import TeamSummaryPublic
from app.models.types import NoneToList, NumToStr
from app.models.user import UserSummaryPublic

if TYPE_CHECKING:
    from app.models.relationships import DBTeamSeasonCaptain
    from app.models.team_season import DBTeamSeason
    from app.models.user_team_season import DBUserTeamSeason


class TeamBase(SQLModel):
    # name and long_name also receive numeric cells from the xlsx import.
    name: str = Field(max_length=50)
    long_name: str | None = Field(default=None, max_length=100)


class Team(TeamBase, DBModel, table=True):
    __tablename__ = "teams"

    id: int | None = Field(default=None, primary_key=True)
    # A team is a named entrant of one league. Its roster may change between
    # that league's events, but the team never exists outside the league.
    league_id: int = Field(index=True, foreign_key="league.id")
    # the public blob the logo is served from
    icon_url: str | None = Field(default=None, max_length=500)
    user_seasons: list["DBUserTeamSeason"] = Relationship(
        back_populates="team",
        sa_relationship_kwargs={"lazy": "raise_on_sql", "cascade": "all, delete"},
    )
    season_info: list["DBTeamSeason"] = Relationship(
        back_populates="team",
        sa_relationship_kwargs={"lazy": "raise_on_sql", "cascade": "all, delete"},
    )
    captain_seasons: list["DBTeamSeasonCaptain"] = Relationship(
        back_populates="team",
        sa_relationship_kwargs={
            "lazy": "raise_on_sql",
            "cascade": "all, delete",
            "order_by": "DBTeamSeasonCaptain.user_id",
        },
    )


class TeamCreate(TeamBase):
    name: Annotated[str, NumToStr] = Field(max_length=50)
    long_name: Annotated[str | None, NumToStr] = Field(default=None, max_length=100)


class TeamUpdate(SQLModel):
    name: Annotated[str | None, NumToStr] = None
    long_name: Annotated[str | None, NumToStr] = None


class TeamPlayerIds(SQLModel):
    player_ids: list[int]


class TeamCaptainIds(SQLModel):
    # An empty list clears the captains, so a missing key reads as one
    captain_ids: list[int] = []


class TeamPublic(TeamSummaryPublic):
    """One team: the summary plus the events it entered."""

    seasons_info: Annotated[list[SeasonInfoPublic], NoneToList] = []
    # Captains whose Discord account still lacks a bound role; only Save Captains fills it
    discord_role_missing: Annotated[list[str], NoneToList] = []

    @classmethod
    def from_team(cls, team: Team) -> Self:
        row = super().from_team(team)
        row.seasons_info = [
            SeasonInfoPublic(season_id=info.season_id) for info in team.season_info
        ]
        return row


class TeamRosterPublic(TeamPublic):
    """A team in one event: who played and captained for it there, under the
    event's id alone. The loader bounds the link rows to that event."""

    player_by_season: dict[int, list[UserSummaryPublic]] = {}
    captains_by_season: dict[int, list[UserSummaryPublic]] = {}

    @classmethod
    def from_roster(cls, team: Team, event_id: int) -> Self:
        row = cls.from_team(team)
        row.player_by_season = {
            event_id: [
                UserSummaryPublic.from_user(seat.user, event_id)
                for seat in team.user_seasons
            ]
        }
        row.captains_by_season = {
            event_id: [
                UserSummaryPublic.from_user(seat.user, event_id)
                for seat in team.captain_seasons
            ]
        }
        return row
