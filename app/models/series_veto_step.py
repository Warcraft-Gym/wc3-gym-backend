"""The map veto of one series: the series_veto_step table.

The order of the steps is the season's pick_ban list, so a row records only
the side that took the step and the map it took. Side A is player1 of the
series, and a map used by any step, ban or pick alike, leaves the board.
"""

from typing import Literal, Self

from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.map import Map


class DBSeriesVetoStep(DBModel, table=True):
    __tablename__ = "series_veto_step"
    series_id: int = Field(
        foreign_key="series.id", ondelete="CASCADE", primary_key=True
    )
    # The steps count from 1, in the order of the season's pick_ban list
    step_no: int = Field(primary_key=True)
    side: str = Field(max_length=1)
    action: str = Field(max_length=4)
    map_id: int = Field(foreign_key="maps.id")
    # Who typed the step in; null when the final step took itself or an admin entered it
    entered_by: int | None = Field(
        default=None, foreign_key="users.id", ondelete="SET NULL"
    )


class SeriesVetoStepPublic(SQLModel):
    step_no: int
    side: str
    action: str
    map_id: int
    entered_by: int | None = None
    shortname: str | None = None
    name: str | None = None

    @classmethod
    def from_row(cls, row: DBSeriesVetoStep, map: Map | None) -> Self:
        return cls(
            step_no=row.step_no,
            side=row.side,
            action=row.action,
            map_id=row.map_id,
            entered_by=row.entered_by,
            shortname=map.shortname if map else None,
            name=map.name if map else None,
        )


class VetoPlayer(SQLModel):
    id: int
    name: str | None = None


class SeriesVetoPublic(SQLModel):
    """Everything the veto board draws: the steps taken and the rules they follow."""

    steps: list[SeriesVetoStepPublic]
    order: list[str]
    # The side the viewer plays, null for an admin, who edits either side
    viewer_side: str | None = None
    on_turn: bool = False
    complete: bool = False
    pool: list[int]
    week_map_id: int | None = None
    map_rules: str | None = None
    player1: VetoPlayer
    player2: VetoPlayer


class SeriesVetoWrite(SQLModel):
    """One move: take the step the order names next, record it for either side
    when the veto happened elsewhere, or take back the last step you entered."""

    token: str | None = None
    action: Literal["step", "record", "undo"]
    map_id: int | None = None
