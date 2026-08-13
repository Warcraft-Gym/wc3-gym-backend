from typing import TYPE_CHECKING

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from src.models.base import DBModel
from src.models.enums import Race
from src.models.relationships import DBUserTeamSeason

if TYPE_CHECKING:
    from src.models.player_career_stats import DBPlayerCareerStats
    from src.models.relationships import DBFantasyTeamPlayer, DBUserSeasonSignup
    from src.models.w3c_stats import DBW3CStats


class DBUser(DBModel):
    __tablename__ = "users"
    __table_args__ = {"mysql_charset": "utf8mb4"}
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    battleTag: Mapped[str] = mapped_column(String(50))
    discordTag: Mapped[str] = mapped_column(String(50))
    discordId: Mapped[str] = mapped_column(String(50))
    race: Mapped[Race] = mapped_column(Enum(Race))
    mmr: Mapped[int | None] = mapped_column()
    country: Mapped[str | None] = mapped_column(String(2))
    fantasy_tier: Mapped[int | None] = mapped_column()
    team_seasons: Mapped[list["DBUserTeamSeason"]] = relationship(
        back_populates="user", cascade="all, delete"
    )
    w3c_stats: Mapped[list["DBW3CStats"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    fantasy_teams: Mapped[list["DBFantasyTeamPlayer"]] = relationship(
        back_populates="users", cascade="all, delete-orphan"
    )
    signup_seasons: Mapped[list["DBUserSeasonSignup"]] = relationship(
        back_populates="user", cascade="all, delete"
    )
    career_stats: Mapped[list["DBPlayerCareerStats"]] = relationship(
        back_populates="user"
    )

    @classmethod
    def updateUserTeamSeasonStats(cls, session: Session, season_stats):
        from src.models.season import DBSeason
        from src.models.team import DBTeam

        team = session.get(DBTeam, season_stats.team_id)
        if not team:
            raise Exception(f"Team not found by id: {season_stats.team_id}")
        season = session.get(DBSeason, season_stats.season_id)
        if not season:
            raise Exception(f"Season not found by id: {season_stats.season_id}")
        user = session.get(cls, season_stats.user_id)
        if not user:
            raise Exception(f"User not found by id: {season_stats.user_id}")
        uts_obj = session.get(
            DBUserTeamSeason,
            {"team_id": team.id, "season_id": season.id, "user_id": user.id},
        )
        if uts_obj is not None:
            uts_obj.games = season_stats.games
            uts_obj.wins = season_stats.wins
            uts_obj.losses = season_stats.losses
            uts_obj.matchup_history = season_stats.matchup_history
        else:
            uts_obj = DBUserTeamSeason(user=user, season=season, team=team)
            uts_obj.games = season_stats.games
            uts_obj.wins = season_stats.wins
            uts_obj.losses = season_stats.losses
            uts_obj.matchup_history = season_stats.matchup_history
            session.add(uts_obj)
        session.flush()
        return uts_obj
