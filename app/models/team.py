from typing import TYPE_CHECKING, Annotated, Any, Self

from pydantic import BeforeValidator
from sqlalchemy.orm import Session
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel, ident
from app.models.season_info import SeasonInfoPublic
from app.models.team_reduced import TeamReduced
from app.models.types import NoneToList, NumToStr
from app.models.user import UserPublic

if TYPE_CHECKING:
    from app.models.relationships import DBTeamSeasonCaptain
    from app.models.team_season import DBTeamSeason
    from app.models.user_team_season import DBUserTeamSeason


def _season_lists(value: Any) -> Any:  # noqa: ANN401  # a validator sees raw input
    """Per-season lists: drop empty seasons and None entries."""
    if not value:
        return {}
    if not isinstance(value, dict):
        return value
    result = {}
    for season, items in value.items():
        if items:
            result[season] = [item for item in items if item is not None]
    return result


SeasonLists = BeforeValidator(_season_lists)


class TeamBase(SQLModel):
    # name and long_name also receive numeric cells from the xlsx import.
    name: Annotated[str, NumToStr] = Field(max_length=50)
    long_name: Annotated[str | None, NumToStr] = Field(default=None, max_length=100)


class Team(TeamBase, DBModel, table=True):
    __tablename__ = "teams"

    id: int | None = Field(default=None, primary_key=True)
    icon: bytes | None = None
    user_seasons: list["DBUserTeamSeason"] = Relationship(
        back_populates="team", sa_relationship_kwargs={"cascade": "all, delete"}
    )
    season_info: list["DBTeamSeason"] = Relationship(
        back_populates="team", sa_relationship_kwargs={"cascade": "all, delete"}
    )
    captain_seasons: list["DBTeamSeasonCaptain"] = Relationship(
        back_populates="team",
        sa_relationship_kwargs={
            "cascade": "all, delete",
            "order_by": "DBTeamSeasonCaptain.user_id",
        },
    )

    @classmethod
    def update_icon(cls, session: Session, obj_id: int, file: bytes) -> Self | None:
        obj = session.get(cls, obj_id)
        if obj:
            obj.icon = file
            session.flush()
        return obj


class TeamCreate(TeamBase):
    pass


class TeamUpdate(SQLModel):
    name: Annotated[str | None, NumToStr] = None
    long_name: Annotated[str | None, NumToStr] = None


class TeamPublic(TeamReduced):
    """A team plus who played and captained for it, season by season.

    The lists are assembled from the link rows rather than read off the
    team, so this one is built by from_team, not by model_validate.
    """

    player_by_season: Annotated[dict[int, list[UserPublic]], SeasonLists] = {}
    captains_by_season: Annotated[dict[int, list[UserPublic]], SeasonLists] = {}
    seasons_info: Annotated[list[SeasonInfoPublic], NoneToList] = []
    # Captains whose Discord account still lacks a bound role; only Save Captains fills it
    discord_role_missing: Annotated[list[str], NoneToList] = []

    @classmethod
    def from_team(cls, team: Team) -> Self:
        players = {}
        captains = {}
        seasons_info = (
            [
                s
                for s in (
                    SeasonInfoPublic.from_team_season(info) for info in team.season_info
                )
                if s
            ]
            if team.season_info
            else []
        )

        if team.user_seasons:
            for ut in team.user_seasons:
                if not players.get(ut.season_id):
                    players[ut.season_id] = []
                # A noload on the link leaves the user unloaded
                user = UserPublic.from_user(ut.user) if ut.user else None
                if user:
                    for gnl_stat in user.gnl_stats:
                        if gnl_stat.season_id == ut.season_id:
                            user.gnl_stats = [gnl_stat]
                            break
                    players[ut.season_id].append(user)

        # Load captains from the team_season_captain rows
        for seat in team.captain_seasons:
            built = UserPublic.from_user(seat.user) if seat.user else None
            if built:
                captains.setdefault(seat.season_id, []).append(built)

        return cls(
            id=ident(team),
            name=team.name,
            long_name=team.long_name,
            player_by_season=players,
            captains_by_season=captains,
            seasons_info=seasons_info,
        )
