"""One stage of an event: one format played over the entrants.

A GNL season has one round_robin stage whose rounds are the playdays. A cup
may have a group stage and a bracket stage, in position order. The points and
the ranking rule are the stage's, so standings are computed, never stored.
"""

from typing import Annotated

from sqlalchemy import UniqueConstraint, false
from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.enums import SchedulingMode, StageFormat
from app.models.types import MapRules, NumToStr


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
