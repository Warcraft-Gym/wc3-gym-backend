from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.models.base import DBModel
from app.models.enums import Race
from app.models.relationships import DBFantasyTeamPlayer
from app.models.user import DBUser

if TYPE_CHECKING:
    from app.models.season import DBSeason
    from app.models.team import DBTeam


class DBFantasyTeam(DBModel):
    __tablename__ = "fantasy_teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id", ondelete="CASCADE"))
    captain_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    drafted_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE")
    )
    drafted_race: Mapped[Race | None] = mapped_column(Enum(Race))
    player_points: Mapped[int | None] = mapped_column()
    bench_points: Mapped[int | None] = mapped_column()
    team_points: Mapped[int | None] = mapped_column()
    race_points: Mapped[int | None] = mapped_column()
    bet_points: Mapped[int | None] = mapped_column()
    total_points: Mapped[int | None] = mapped_column()

    drafted_team: Mapped["DBTeam | None"] = relationship(foreign_keys=[drafted_team_id])
    captain: Mapped["DBUser"] = relationship(foreign_keys=[captain_id])
    season: Mapped["DBSeason"] = relationship(foreign_keys=[season_id])
    drafted_players: Mapped[list["DBFantasyTeamPlayer"]] = relationship(
        back_populates="fantasy_team", cascade="all, delete"
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
            user = session.get(DBUser, user_id)
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
            user = session.get(DBUser, user_id)
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
