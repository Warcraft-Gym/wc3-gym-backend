"""Link tables, each keyed by the two ids it joins.

The link tables with a model's worth of columns are in their own files:
team_season.py and user_team_season.py.
"""

from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship

from app.models.base import DBModel
from app.models.enums import Race

if TYPE_CHECKING:
    from app.models.fantasy_team import FantasyTeam
    from app.models.map import Map
    from app.models.season import Season
    from app.models.team import Team
    from app.models.user import User


class DBUserSeasonSignup(DBModel, table=True):
    __tablename__ = "user_season_signup"
    user_id: int = Field(foreign_key="users.id", primary_key=True)
    season_id: int = Field(index=True, foreign_key="seasons.id", primary_key=True)
    # The race the player registered on for this season, null when not recorded
    race: Race | None = None
    user: "User" = Relationship(back_populates="signup_seasons")
    season: "Season" = Relationship(back_populates="signup_users")


class DBTeamSeasonCoach(DBModel, table=True):
    __tablename__ = "team_season_coach"
    team_id: int = Field(foreign_key="teams.id", primary_key=True)
    season_id: int = Field(index=True, foreign_key="seasons.id", primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id", primary_key=True)
    team: "Team" = Relationship(back_populates="coach_seasons")
    user: "User" = Relationship()


class DBMapSeason(DBModel, table=True):
    __tablename__ = "map_season"
    map_id: int = Field(foreign_key="maps.id", primary_key=True)
    season_id: int = Field(index=True, foreign_key="seasons.id", primary_key=True)
    season: "Season" = Relationship(back_populates="maps")
    map: "Map" = Relationship(back_populates="seasons")


class DBFantasyTeamPlayer(DBModel, table=True):
    __tablename__ = "fantasy_team_player"
    fantasy_team_id: int = Field(foreign_key="fantasy_teams.id", primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id", primary_key=True)
    # Additional columns can be added here if needed
    fantasy_team: "FantasyTeam" = Relationship(back_populates="drafted_players")
    users: "User" = Relationship(back_populates="fantasy_teams")
