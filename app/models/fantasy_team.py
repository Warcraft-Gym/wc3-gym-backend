from typing import TYPE_CHECKING, Annotated, Any, Self

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.enums import Race
from app.models.season import SeasonPublic
from app.models.team import Team, TeamPublic
from app.models.types import NoneToList, NumToStr
from app.models.user import UserPublic

if TYPE_CHECKING:
    from app.models.relationships import DBFantasyTeamPlayer
    from app.models.season import Season
    from app.models.user import User


class FantasyTeamBase(SQLModel):
    name: Annotated[str, NumToStr] = Field(max_length=100)
    season_id: int = Field(foreign_key="seasons.id", ondelete="CASCADE")
    captain_id: int = Field(foreign_key="users.id", ondelete="CASCADE")
    drafted_team_id: int | None = Field(
        default=None, foreign_key="teams.id", ondelete="CASCADE"
    )
    player_points: int | None = None
    bench_points: int | None = None
    team_points: int | None = None
    race_points: int | None = None
    bet_points: int | None = None
    total_points: int | None = None


class FantasyTeam(FantasyTeamBase, DBModel, table=True):
    __tablename__ = "fantasy_teams"

    id: int | None = Field(default=None, primary_key=True)
    drafted_race: Race | None = None

    drafted_team: Team | None = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[FantasyTeam.drafted_team_id]"}
    )
    captain: "User" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[FantasyTeam.captain_id]"}
    )
    season: "Season" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[FantasyTeam.season_id]"}
    )
    drafted_players: list["DBFantasyTeamPlayer"] = Relationship(
        back_populates="fantasy_team",
        sa_relationship_kwargs={"cascade": "all, delete"},
    )


class FantasyTeamPlayerIds(SQLModel):
    player_ids: list[int]


class FantasyTeamCreate(FantasyTeamBase):
    # A Race member when the value comes from the database, a plain string
    # when it comes from request JSON.
    drafted_race: Race | str | None = None


class FantasyTeamUpdate(SQLModel):
    name: Annotated[str | None, NumToStr] = None
    season_id: int | None = None
    captain_id: int | None = None
    drafted_team_id: int | None = None
    drafted_race: Race | str | None = None
    player_points: int | None = None
    bench_points: int | None = None
    team_points: int | None = None
    race_points: int | None = None
    bet_points: int | None = None
    total_points: int | None = None


class FantasyTeamPublic(FantasyTeamBase):
    id: int | None = None
    name: Annotated[str | None, NumToStr] = None
    season_id: int | None = None
    captain_id: int | None = None
    drafted_race: Race | str | None = None
    season: SeasonPublic | None = None
    captain: UserPublic | None = None
    drafted_team: TeamPublic | None = None
    drafted_players: Annotated[list[UserPublic], NoneToList] = []

    @classmethod
    def from_fantasy_team(cls, fteam: FantasyTeam | None) -> Self | None:
        if not fteam:
            return None

        drafted_players = []
        if fteam.drafted_players:
            for dp in fteam.drafted_players:
                user = UserPublic.from_user(dp.users)
                if user:
                    drafted_players.append(user)

        return cls(
            id=fteam.id,
            name=fteam.name,
            season_id=fteam.season_id,
            season=SeasonPublic.from_season(fteam.season) if fteam.season else None,
            captain_id=fteam.captain_id,
            captain=UserPublic.from_user(fteam.captain) if fteam.captain else None,
            drafted_team_id=fteam.drafted_team_id,
            drafted_team=TeamPublic.from_team(fteam.drafted_team)
            if fteam.drafted_team
            else None,
            drafted_race=fteam.drafted_race,
            drafted_players=drafted_players,
            player_points=fteam.player_points,
            bench_points=fteam.bench_points,
            team_points=fteam.team_points,
            race_points=fteam.race_points,
            bet_points=fteam.bet_points,
            total_points=fteam.total_points,
        )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
