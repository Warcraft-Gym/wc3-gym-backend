"""One stage of an event: one format played over the entrants.

A GNL season has one round_robin stage whose rounds are the playdays. A cup
may have a group stage and a bracket stage, in position order. The points and
the ranking rule are the stage's, so standings are computed, never stored.
"""

from datetime import datetime
from typing import Annotated

from sqlalchemy import UniqueConstraint, false
from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.enums import SchedulingMode, StageFormat
from app.models.types import AwareUTC, MapRules, NumToStr, UTCDateTime


class EventStage(DBModel, table=True):
    __tablename__ = "event_stage"
    __table_args__ = (UniqueConstraint("event_id", "position"),)

    id: int | None = Field(default=None, primary_key=True)
    event_id: int = Field(index=True, foreign_key="event.id", ondelete="CASCADE")
    # Stages play in this order; the first is position 1
    position: int = Field(default=1)
    name: Annotated[str | None, NumToStr] = Field(default=None, max_length=50)
    format: StageFormat = Field(
        default=StageFormat.round_robin,
        sa_column_kwargs={"server_default": "round_robin"},
    )
    best_of: int = Field(default=3, sa_column_kwargs={"server_default": "3"})
    # One rule per game of a series: veto, loser, host or fixed
    map_rules: Annotated[str | None, MapRules] = Field(default=None, max_length=100)
    scheduling_mode: SchedulingMode = Field(
        default=SchedulingMode.agreed, sa_column_kwargs={"server_default": "agreed"}
    )
    # The tie breaks the standings read, in order
    ranking_rule: str = Field(
        default="points,game_diff,head_to_head",
        max_length=100,
        sa_column_kwargs={"server_default": "points,game_diff,head_to_head"},
    )
    points_series_won: int = Field(default=1, sa_column_kwargs={"server_default": "1"})
    points_series_drawn: int = Field(
        default=0, sa_column_kwargs={"server_default": "0"}
    )
    points_game_won: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    # How many of the standings carry into the next stage; null means all of them
    advance_count: int | None = None
    # How the stage splits into groups that merge at the next stage; unused until
    # the group generator is built
    group_size: int | None = None
    group_advance: int | None = None
    # On: finishing the stage carries the advance_count into the next one
    auto_advance: bool = Field(
        default=False, sa_column_kwargs={"server_default": false()}
    )
    # When an admin locked the seeds; a locked stage refuses a seed write
    seeds_locked_at: Annotated[datetime | None, AwareUTC] = Field(
        default=None, sa_type=UTCDateTime
    )
    # On: an elimination bracket adds the series the beaten semi-finalists play
    third_place: bool = Field(
        default=False, sa_column_kwargs={"server_default": false()}
    )
    # What a double elimination final holds: one series, a reset, or none
    grand_final_modifier: str = Field(
        default="one", max_length=10, sa_column_kwargs={"server_default": "one"}
    )


class EventStagePublic(SQLModel):
    """One stage as the event page reads it; the standings are computed elsewhere."""

    id: int
    position: int
    name: Annotated[str | None, NumToStr] = None
    format: StageFormat
    best_of: int
    map_rules: Annotated[str | None, MapRules] = None
    scheduling_mode: SchedulingMode
    ranking_rule: str
    points_series_won: int
    points_series_drawn: int
    points_game_won: int
    advance_count: int | None = None
    group_size: int | None = None
    group_advance: int | None = None
    auto_advance: bool = False
    seeds_locked_at: Annotated[datetime | None, AwareUTC] = None
    third_place: bool = False
    grand_final_modifier: str = "one"


class EventStageWrite(SQLModel):
    """One stage as an admin writes it; its place in the list is its position."""

    name: Annotated[str | None, NumToStr] = None
    format: StageFormat = StageFormat.round_robin
    best_of: int = 3
    map_rules: Annotated[str | None, MapRules] = None
    scheduling_mode: SchedulingMode = SchedulingMode.agreed
    ranking_rule: str = "points,game_diff,head_to_head"
    points_series_won: int = 1
    points_series_drawn: int = 0
    points_game_won: int = 0
    advance_count: int | None = None


class StandingRow(SQLModel):
    """One entrant's line of a stage table, computed on every read."""

    position: int
    entrant_id: int
    user_id: int | None = None
    team_id: int | None = None
    name: Annotated[str | None, NumToStr] = None
    played: int = 0
    won: int = 0
    lost: int = 0
    games_won: int = 0
    games_lost: int = 0
    points: int = 0
    game_diff: int = 0


class DivisionStandings(SQLModel):
    """The table of one division; a stage with no divisions answers one of these."""

    division_id: int | None = None
    division_name: Annotated[str | None, NumToStr] = None
    rows: list[StandingRow] = []
