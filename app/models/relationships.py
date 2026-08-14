from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import JSON, Column, select
from sqlalchemy.orm import Session, joinedload
from sqlmodel import Field, Relationship

from app.models.base import DBModel

if TYPE_CHECKING:
    from app.models.fantasy_team import DBFantasyTeam
    from app.models.map import DBMap
    from app.models.season import DBSeason
    from app.models.team import DBTeam
    from app.models.user import DBUser


class DBUserTeamSeason(DBModel, table=True):
    __tablename__ = "user_team_season"
    user_id: int = Field(foreign_key="users.id", primary_key=True)
    team_id: int = Field(foreign_key="teams.id", primary_key=True)
    season_id: int = Field(foreign_key="seasons.id", primary_key=True)
    games: int | None = None
    wins: int | None = None
    losses: int | None = None
    # Array of opponent races: ['HU', 'OC', 'UD', etc.]
    matchup_history: list[Any] | None = Field(
        default=None, sa_column=Column("matchup_history", JSON)
    )
    # Additional columns can be added here if needed
    user: "DBUser" = Relationship(back_populates="team_seasons")
    team: "DBTeam" = Relationship(back_populates="user_seasons")
    season: "DBSeason" = Relationship(back_populates="user_teams")


class DBUserSeasonSignup(DBModel, table=True):
    __tablename__ = "user_season_signup"
    user_id: int = Field(foreign_key="users.id", primary_key=True)
    season_id: int = Field(foreign_key="seasons.id", primary_key=True)
    # Additional columns can be added here if needed
    user: "DBUser" = Relationship(back_populates="signup_seasons")
    season: "DBSeason" = Relationship(back_populates="signup_users")


class DBTeamSeason(DBModel, table=True):
    __tablename__ = "team_season"
    team_id: int = Field(foreign_key="teams.id", primary_key=True)
    season_id: int = Field(foreign_key="seasons.id", primary_key=True)
    # Team coaches (up to 3)
    coach_1_id: int | None = Field(default=None, foreign_key="users.id")
    coach_2_id: int | None = Field(default=None, foreign_key="users.id")
    coach_3_id: int | None = Field(default=None, foreign_key="users.id")
    # Additional columns
    final_score: int | None = None
    points_available: int | None = None
    points_against: int | None = None
    maps_won: int | None = None
    maps_lost: int | None = None
    # Relationships
    team: "DBTeam" = Relationship(back_populates="season_info")
    season: "DBSeason" = Relationship(back_populates="teams")
    coach_1: Optional["DBUser"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBTeamSeason.coach_1_id]"}
    )
    coach_2: Optional["DBUser"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBTeamSeason.coach_2_id]"}
    )
    coach_3: Optional["DBUser"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBTeamSeason.coach_3_id]"}
    )

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


class DBMapSeason(DBModel, table=True):
    __tablename__ = "map_season"
    map_id: int = Field(foreign_key="maps.id", primary_key=True)
    season_id: int = Field(foreign_key="seasons.id", primary_key=True)
    season: "DBSeason" = Relationship(back_populates="maps")
    map: "DBMap" = Relationship(back_populates="seasons")


class DBFantasyTeamPlayer(DBModel, table=True):
    __tablename__ = "fantasy_team_player"
    fantasy_team_id: int = Field(foreign_key="fantasy_teams.id", primary_key=True)
    user_id: int = Field(foreign_key="users.id", primary_key=True)
    # Additional columns can be added here if needed
    fantasy_team: "DBFantasyTeam" = Relationship(back_populates="drafted_players")
    users: "DBUser" = Relationship(back_populates="fantasy_teams")
