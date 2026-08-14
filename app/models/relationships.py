from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, select
from sqlalchemy.orm import Mapped, Session, joinedload, mapped_column, relationship

from app.models.base import DBModel

if TYPE_CHECKING:
    from app.models.fantasy_team import DBFantasyTeam
    from app.models.map import DBMap
    from app.models.season import DBSeason
    from app.models.team import DBTeam
    from app.models.user import DBUser


class DBUserTeamSeason(DBModel):
    __tablename__ = "user_team_season"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), primary_key=True)
    games: Mapped[int | None] = mapped_column()
    wins: Mapped[int | None] = mapped_column()
    losses: Mapped[int | None] = mapped_column()
    matchup_history: Mapped[list | None] = mapped_column(
        JSON
    )  # Array of opponent races: ['HU', 'OC', 'UD', etc.]
    # Additional columns can be added here if needed
    user: Mapped["DBUser"] = relationship(back_populates="team_seasons")
    team: Mapped["DBTeam"] = relationship(back_populates="user_seasons")
    season: Mapped["DBSeason"] = relationship(back_populates="user_teams")


class DBUserSeasonSignup(DBModel):
    __tablename__ = "user_season_signup"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), primary_key=True)
    # Additional columns can be added here if needed
    user: Mapped["DBUser"] = relationship(back_populates="signup_seasons")
    season: Mapped["DBSeason"] = relationship(back_populates="signup_users")


class DBTeamSeason(DBModel):
    __tablename__ = "team_season"
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), primary_key=True)
    # Team coaches (up to 3)
    coach_1_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    coach_2_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    coach_3_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    # Additional columns
    final_score: Mapped[int | None] = mapped_column()
    points_available: Mapped[int | None] = mapped_column()
    points_against: Mapped[int | None] = mapped_column()
    maps_won: Mapped[int | None] = mapped_column()
    maps_lost: Mapped[int | None] = mapped_column()
    # Relationships
    team: Mapped["DBTeam"] = relationship(back_populates="season_info")
    season: Mapped["DBSeason"] = relationship(back_populates="teams")
    coach_1: Mapped["DBUser | None"] = relationship(foreign_keys=[coach_1_id])
    coach_2: Mapped["DBUser | None"] = relationship(foreign_keys=[coach_2_id])
    coach_3: Mapped["DBUser | None"] = relationship(foreign_keys=[coach_3_id])

    @classmethod
    def updateSeasonInfo(cls, session: Session, obj_id, team_id, **kwargs):
        # Eager load related entities to prevent N+1 queries
        obj = session.scalars(
            select(cls)
            .options(joinedload(cls.team), joinedload(cls.season))
            .where(cls.team_id == team_id, cls.season_id == obj_id)
            .limit(1)
        ).first()
        if obj:
            for key, value in kwargs.items():
                setattr(obj, key, value)
            session.flush()
        return obj


class DBMapSeason(DBModel):
    __tablename__ = "map_season"
    map_id: Mapped[int] = mapped_column(ForeignKey("maps.id"), primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), primary_key=True)
    season: Mapped["DBSeason"] = relationship(back_populates="maps")
    map: Mapped["DBMap"] = relationship(back_populates="seasons")


class DBFantasyTeamPlayer(DBModel):
    __tablename__ = "fantasy_team_player"
    fantasy_team_id: Mapped[int] = mapped_column(
        ForeignKey("fantasy_teams.id"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    # Additional columns can be added here if needed
    fantasy_team: Mapped["DBFantasyTeam"] = relationship(
        back_populates="drafted_players"
    )
    users: Mapped["DBUser"] = relationship(back_populates="fantasy_teams")
