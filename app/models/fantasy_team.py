from typing import TYPE_CHECKING, Optional

from sqlalchemy.orm import Session
from sqlmodel import Field, Relationship

from app.models.base import DBModel
from app.models.enums import Race
from app.models.relationships import DBFantasyTeamPlayer
from app.models.user import User

if TYPE_CHECKING:
    from app.models.season import Season
    from app.models.team import Team


class DBFantasyTeam(DBModel, table=True):
    __tablename__ = "fantasy_teams"
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    season_id: int = Field(foreign_key="seasons.id", ondelete="CASCADE")
    captain_id: int = Field(foreign_key="users.id", ondelete="CASCADE")
    drafted_team_id: int | None = Field(
        default=None, foreign_key="teams.id", ondelete="CASCADE"
    )
    drafted_race: Race | None = None
    player_points: int | None = None
    bench_points: int | None = None
    team_points: int | None = None
    race_points: int | None = None
    bet_points: int | None = None
    total_points: int | None = None

    drafted_team: Optional["Team"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBFantasyTeam.drafted_team_id]"}
    )
    captain: "User" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBFantasyTeam.captain_id]"}
    )
    season: "Season" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBFantasyTeam.season_id]"}
    )
    drafted_players: list["DBFantasyTeamPlayer"] = Relationship(
        back_populates="fantasy_team",
        sa_relationship_kwargs={"cascade": "all, delete"},
    )

    def to_dict(self):
        return {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }

    @classmethod
    def addPlayers(cls, session: Session, obj_id, user_ids):
        team = session.get(cls, obj_id)
        if not team:
            raise Exception(f"Team not found by id: {obj_id}")
        for user_id in user_ids:
            user = session.get(User, user_id)
            if not user:
                raise Exception(f"User not found by id: {user_id}")
            already_exists = (
                session.get(
                    DBFantasyTeamPlayer,
                    {"fantasy_team_id": team.id, "user_id": user.id},
                )
                is not None
            )
            if not already_exists:
                session.add(DBFantasyTeamPlayer(users=user, fantasy_team=team))

        session.flush()
        return team

    @classmethod
    def removePlayers(cls, session: Session, obj_id, user_ids):
        team = session.get(cls, obj_id)
        if not team:
            raise Exception(f"Fantasy Team not found by id: {obj_id}")
        for user_id in user_ids:
            user = session.get(User, user_id)
            if not user:
                raise Exception(f"User not found by id: {user_id}")
            user_team = session.get(
                DBFantasyTeamPlayer, {"fantasy_team_id": obj_id, "user_id": user.id}
            )
            if not user_team:
                raise Exception(
                    f"User not part of the fantasy team, user id: {user_id}"
                )
            session.delete(user_team)
        session.flush()
        return team
