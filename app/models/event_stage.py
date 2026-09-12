"""One stage of an event: one format played over the entrants.

A GNL season has one round_robin stage whose rounds are the playdays. A cup
may have a group stage and a bracket stage, in position order. The points and
the ranking rule are the stage's, so standings are computed, never stored.
"""

from typing import Annotated

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

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
