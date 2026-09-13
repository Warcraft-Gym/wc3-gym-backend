"""Link tables, each keyed by the two ids it joins.

The link tables with a model's worth of columns are in their own files:
team_season.py and user_team_season.py.
"""

from datetime import date
from typing import TYPE_CHECKING, Annotated, Self

from sqlalchemy import UniqueConstraint, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import Field, Relationship, SQLModel, col

from app.models.base import DBModel
from app.models.enums import Race
from app.models.types import IsoDate, LenientDate

if TYPE_CHECKING:
    from app.models.fantasy_team import FantasyTeam
    from app.models.map import Map
    from app.models.season import Season
    from app.models.team import Team
    from app.models.user import User


class DBUserSeasonSignup(DBModel, table=True):
    __tablename__ = "user_season_signup"
    user_id: int = Field(foreign_key="users.id", primary_key=True)
    season_id: int = Field(index=True, foreign_key="event.id", primary_key=True)
    # The race the player registered on for this season
    race: Race
    # The fantasy tier this season cut the player into, null when not allocated
    fantasy_tier: int | None = None
    # The slot an admin moved the player to in the draft order; null sorts by MMR
    draft_position: int | None = None
    # An admin took the player out of the pick list, so he holds no draft slot
    draft_excluded: bool = Field(
        default=False, sa_column_kwargs={"server_default": "false"}
    )
    user: "User" = Relationship(back_populates="signup_seasons")
    season: "Season" = Relationship(back_populates="signup_users")


class DBTeamSeasonCaptain(DBModel, table=True):
    __tablename__ = "team_season_captain"
    team_id: int = Field(foreign_key="teams.id", primary_key=True)
    season_id: int = Field(index=True, foreign_key="event.id", primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id", primary_key=True)
    team: "Team" = Relationship(back_populates="captain_seasons")
    user: "User" = Relationship()


class DBMapSeason(DBModel, table=True):
    __tablename__ = "map_season"
    map_id: int = Field(foreign_key="maps.id", primary_key=True)
    season_id: int = Field(index=True, foreign_key="event.id", primary_key=True)
    # The place of the map in the pool; the season service appends at the end
    position: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    season: "Season" = Relationship(back_populates="maps")
    map: "Map" = Relationship(back_populates="seasons")


class DBEventRound(DBModel, table=True):
    """One scheduled round of a stage: its number, its window and game 1's map.

    Renamed from season_rounds in C1, which gave it an id. season_id stays
    beside stage_id until every reader keys on the stage, so the season_rounds
    view the running deploy reads is still one plain select over this table.
    """

    __tablename__ = "event_round"
    # The key the rounds were stored under before the id; C2 adds (stage_id, number)
    __table_args__ = (
        UniqueConstraint("season_id", "number", name="uq_event_round_season_id_number"),
    )

    id: int | None = Field(default=None, primary_key=True)
    # Null while the season_rounds view still takes inserts; C2 refuses a null
    stage_id: int | None = Field(
        default=None, index=True, foreign_key="event_stage.id", ondelete="CASCADE"
    )
    season_id: int = Field(foreign_key="event.id")
    # The place of the round in its stage; the GNL playday
    number: int
    name: str | None = Field(default=None, max_length=50)
    # The window the round is played in; no end date means a one-day round
    start_date: date | None = None
    end_date: date | None = None
    map_id: int | None = Field(
        default=None, index=True, foreign_key="maps.id", ondelete="SET NULL"
    )
    # Overrides the stage's best of for this round; null follows the stage
    best_of: int | None = None
    season: "Season" = Relationship(back_populates="rounds")


def round_row(session: OrmSession, season_id: int, number: int) -> DBEventRound | None:
    """The round of one event by its number. The table is keyed by an id now,
    so the pair no longer reads as a primary key."""
    return session.scalars(
        select(DBEventRound).where(
            col(DBEventRound.season_id) == season_id,
            col(DBEventRound.number) == number,
        )
    ).first()


class SeasonRoundPublic(SQLModel):
    playday: int
    start_date: Annotated[IsoDate | None, LenientDate] = None
    end_date: Annotated[IsoDate | None, LenientDate] = None
    map_id: int | None = None

    @classmethod
    def from_row(cls, row: DBEventRound) -> Self:
        return cls(
            playday=row.number,
            start_date=row.start_date,
            end_date=row.end_date,
            map_id=row.map_id,
        )


class SeasonRoundWrite(SQLModel):
    """One round's settings. A field left out keeps its value; a null clears it."""

    playday: int
    start_date: Annotated[date | None, LenientDate] = None
    end_date: Annotated[date | None, LenientDate] = None
    map_id: int | None = None


class DBFantasyTeamPlayer(DBModel, table=True):
    __tablename__ = "fantasy_team_player"
    fantasy_team_id: int = Field(foreign_key="fantasy_teams.id", primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id", primary_key=True)
    # Additional columns can be added here if needed
    fantasy_team: "FantasyTeam" = Relationship(back_populates="drafted_players")
    users: "User" = Relationship(back_populates="fantasy_teams")
