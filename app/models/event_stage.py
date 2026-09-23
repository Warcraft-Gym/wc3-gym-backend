"""One stage of an event: one format played over the entrants.

A GNL season has one round_robin stage whose rounds are the playdays. A cup
may have a group stage and a bracket stage, in position order. The points and
the ranking rule are the stage's, so standings are computed, never stored.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import model_validator
from sqlalchemy import UniqueConstraint, false
from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.enums import SchedulingMode, StageFormat
from app.models.types import AwareUTC, MapRules, NumToStr, PlacePoints, UTCDateTime

# The tie breaks a table reads by default, in order. The words a rule takes are
# points, buchholz (the sum of the opponents' points), game_diff and
# head_to_head, which runs last of all, inside the group the others leave tied.
RANKING_RULE = "points,game_diff,head_to_head"
# What a stage that draws round by round reads where it names no rule of its own
SWISS_RANKING_RULE = "points,buchholz,game_diff,head_to_head"
# The largest MMR difference a captain draft pairs inside where the stage names none
MAX_MMR_DIFFERENCE = 100


class EventStage(DBModel, table=True):
    __tablename__ = "event_stage"
    __table_args__ = (UniqueConstraint("event_id", "position"),)

    id: int | None = Field(default=None, primary_key=True)
    event_id: int = Field(index=True, foreign_key="event.id", ondelete="CASCADE")
    # Stages play in this order; the first is position 1
    position: int = Field(default=1)
    name: str | None = Field(default=None, max_length=50)
    format: StageFormat = Field(
        default=StageFormat.round_robin,
        sa_column_kwargs={"server_default": "round_robin"},
    )
    best_of: int = Field(default=3, sa_column_kwargs={"server_default": "3"})
    # How many series each entrant plays per round of a round robin stage
    series_per_entrant_per_round: int = Field(
        default=1, ge=1, sa_column_kwargs={"server_default": "1"}
    )
    # How many rounds a Swiss stage draws; null means it draws on without end
    swiss_rounds: int | None = None
    # What each place of an FFA lobby pays, best place first, as "4,3,2,1"
    points_by_place: str | None = Field(default=None, max_length=50)
    # How many players an FFA lobby seats
    lobby_size: int | None = None
    # One rule per game of a series: veto, loser, host or fixed
    map_rules: str | None = Field(default=None, max_length=100)
    scheduling_mode: SchedulingMode = Field(
        default=SchedulingMode.agreed, sa_column_kwargs={"server_default": "agreed"}
    )
    # The tie breaks the standings read, in order; RANKING_RULE names the words
    ranking_rule: str = Field(
        default=RANKING_RULE,
        max_length=100,
        sa_column_kwargs={"server_default": RANKING_RULE},
    )
    points_series_won: int = Field(default=1, sa_column_kwargs={"server_default": "1"})
    points_series_drawn: int = Field(
        default=0, sa_column_kwargs={"server_default": "0"}
    )
    points_game_won: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    # How many of the standings carry into the next stage; null means all of them
    advance_count: int | None = None
    # How the stage splits into groups that merge at the next stage: how many
    # entrants a group seats, and how many of them the next stage takes
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
    # The largest MMR difference a captain draft pairs inside; a gnl stage only
    max_mmr_difference: int | None = None


class EventStagePublic(SQLModel):
    """One stage as the event page reads it; the standings are computed elsewhere."""

    id: int
    position: int
    name: str | None = None
    format: StageFormat
    best_of: int
    series_per_entrant_per_round: int = 1
    swiss_rounds: int | None = None
    points_by_place: str | None = None
    lobby_size: int | None = None
    map_rules: str | None = None
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
    # Null on every format but gnl, where an unset stage reads the default
    max_mmr_difference: int | None = None

    @model_validator(mode="after")
    def _default_max_mmr_difference(self) -> "EventStagePublic":
        if self.format == StageFormat.gnl and self.max_mmr_difference is None:
            self.max_mmr_difference = MAX_MMR_DIFFERENCE
        return self


class EventStageWrite(SQLModel):
    """One stage as an admin writes it; its place in the list is its position."""

    name: Annotated[str | None, NumToStr] = None
    format: StageFormat = StageFormat.round_robin
    best_of: int = 3
    series_per_entrant_per_round: int = Field(default=1, ge=1)
    swiss_rounds: int | None = Field(default=None, ge=1)
    points_by_place: Annotated[str | None, PlacePoints] = Field(
        default=None, max_length=50
    )
    lobby_size: int | None = Field(default=None, ge=2)
    # How many places of one lobby or one group play on; advance_count stays
    # the count the whole stage carries into the next one
    group_advance: int | None = Field(default=None, ge=1)
    map_rules: Annotated[str | None, MapRules] = None
    scheduling_mode: SchedulingMode = SchedulingMode.agreed
    ranking_rule: str = RANKING_RULE
    points_series_won: int = 1
    points_series_drawn: int = 0
    points_game_won: int = 0
    advance_count: int | None = None
    group_size: int | None = Field(default=None, ge=2)
    auto_advance: bool = False
    third_place: bool = False
    grand_final_modifier: Literal["one", "reset", "skip"] = "one"
    # The largest MMR difference a captain draft pairs inside; a gnl stage only
    max_mmr_difference: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _gnl_only_max_mmr_difference(self) -> "EventStageWrite":
        if self.max_mmr_difference is not None and self.format != StageFormat.gnl:
            raise ValueError("max_mmr_difference belongs to a gnl stage only")
        return self


class StandingRow(SQLModel):
    """One entrant's line of a stage table, computed on every read."""

    position: int
    entrant_id: int
    user_id: int | None = None
    team_id: int | None = None
    name: str | None = None
    played: int = 0
    won: int = 0
    lost: int = 0
    games_won: int = 0
    games_lost: int = 0
    points: int = 0
    game_diff: int = 0


class DivisionStandings(SQLModel):
    """The table of one division; a stage with no divisions answers one of these.

    A stage split into groups answers one of these per group, so the table
    names the group it ranks beside the division it belongs to.
    """

    division_id: int | None = None
    division_name: str | None = None
    group_no: int | None = None
    group_name: str | None = None
    rows: list[StandingRow] = []
