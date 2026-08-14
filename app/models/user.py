from typing import TYPE_CHECKING

from sqlalchemy.orm import Session
from sqlmodel import Field, Relationship

from app.models.base import DBModel
from app.models.enums import Race
from app.models.relationships import DBUserTeamSeason

if TYPE_CHECKING:
    from app.models.player_career_stats import DBPlayerCareerStats
    from app.models.relationships import DBFantasyTeamPlayer, DBUserSeasonSignup
    from app.models.w3c_stats import W3CStats


class DBUser(DBModel, table=True):
    __tablename__ = "users"
    __table_args__ = {"mysql_charset": "utf8mb4"}
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=50)
    battleTag: str = Field(max_length=50)
    discordTag: str = Field(max_length=50)
    discordId: str = Field(max_length=50)
    race: Race
    mmr: int | None = None
    country: str | None = Field(default=None, max_length=2)
    fantasy_tier: int | None = None
    team_seasons: list["DBUserTeamSeason"] = Relationship(
        back_populates="user", sa_relationship_kwargs={"cascade": "all, delete"}
    )
    w3c_stats: list["W3CStats"] = Relationship(
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
    career_stats: list["DBPlayerCareerStats"] = Relationship(back_populates="user")

    @classmethod
    def updateUserTeamSeasonStats(cls, session: Session, season_stats):
        from app.models.season import DBSeason
        from app.models.team import DBTeam

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
