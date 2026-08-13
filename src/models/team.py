from typing import TYPE_CHECKING

from sqlalchemy import LargeBinary, String
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from src.models.base import DBModel
from src.models.relationships import DBUserTeamSeason
from src.models.user import DBUser

if TYPE_CHECKING:
    from src.models.relationships import DBTeamSeason


class DBTeam(DBModel):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    long_name: Mapped[str | None] = mapped_column(String(100))
    icon: Mapped[bytes | None] = mapped_column(LargeBinary)
    discord_role: Mapped[str | None] = mapped_column(String(50))
    user_seasons: Mapped[list["DBUserTeamSeason"]] = relationship(
        back_populates="team", cascade="all, delete"
    )
    season_info: Mapped[list["DBTeamSeason"]] = relationship(
        back_populates="team", cascade="all, delete"
    )

    def to_dict(self):
        return {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }

    @classmethod
    def addPlayers(cls, session: Session, obj_id, season_id, user_ids):
        from src.models.season import DBSeason

        team = session.get(cls, obj_id)
        if not team:
            raise Exception(f"Team not found by id: {obj_id}")
        season = session.get(DBSeason, season_id)
        if not season:
            raise Exception(f"Season not found by id: {season_id}")
        for user_id in user_ids:
            user = session.get(DBUser, user_id)
            if not user:
                raise Exception(f"User not found by id: {user_id}")
            already_exists = (
                session.get(
                    DBUserTeamSeason,
                    {"team_id": team.id, "season_id": season_id, "user_id": user.id},
                )
                is not None
            )
            if not already_exists:
                session.add(DBUserTeamSeason(user=user, season=season, team=team))

        session.flush()
        return team

    @classmethod
    def removePlayers(cls, session: Session, obj_id, season_id, user_ids):
        from src.models.season import DBSeason

        team = session.get(cls, obj_id)
        if not team:
            raise Exception(f"Team not found by id: {obj_id}")
        season = session.get(DBSeason, season_id)
        if not season:
            raise Exception(f"Season not found by id: {season_id}")
        for user_id in user_ids:
            user = session.get(DBUser, user_id)
            if not user:
                raise Exception(f"User not found by id: {user_id}")
            user_team = session.get(
                DBUserTeamSeason,
                {"team_id": obj_id, "season_id": season_id, "user_id": user.id},
            )
            if not user_team:
                raise Exception(f"User not part of the team, user id: {user_id}")
            session.delete(user_team)
        session.flush()
        return team

    @classmethod
    def update_icon(cls, session: Session, obj_id, file):
        obj = session.get(cls, obj_id)
        if obj:
            setattr(obj, DBTeam.icon.name, file)
            session.flush()
        return obj

    @classmethod
    def setCoaches(cls, session: Session, team_id, season_id, user_ids):
        """Set coaches for a team in a season (up to 3)."""
        from src.models.relationships import DBTeamSeason
        from src.models.season import DBSeason

        team = session.get(cls, team_id)
        if not team:
            raise Exception(f"Team not found by id: {team_id}")
        season = session.get(DBSeason, season_id)
        if not season:
            raise Exception(f"Season not found by id: {season_id}")

        # Validate coach limit
        if len(user_ids) > 3:
            raise Exception("Cannot assign more than 3 coaches per team per season")

        # Validate all users exist
        for user_id in user_ids:
            user = session.get(DBUser, user_id)
            if not user:
                raise Exception(f"User not found by id: {user_id}")

        # Get or create team_season entry
        team_season = session.get(
            DBTeamSeason, {"team_id": team_id, "season_id": season_id}
        )

        if not team_season:
            team_season = DBTeamSeason(team_id=team_id, season_id=season_id)
            session.add(team_season)

        # Set coaches (pad with None if less than 3)
        team_season.coach_1_id = user_ids[0] if len(user_ids) > 0 else None
        team_season.coach_2_id = user_ids[1] if len(user_ids) > 1 else None
        team_season.coach_3_id = user_ids[2] if len(user_ids) > 2 else None

        session.flush()
        return team
