"""A cup's overall table: the points its players earned over its finished rounds.

Kept apart from `cup_rounds`, because the event payload reads the rounds and a
user summary reads the event.
"""

from sqlmodel import SQLModel

from app.models.cup_rounds import CupLegPublic
from app.models.user import UserSummaryPublic


class OverallLeg(SQLModel):
    """One entrant's result in one finished round: its place and the points it paid."""

    leg_id: int
    place: int
    points: int


class OverallRow(SQLModel):
    """One line of a cup's overall table."""

    position: int
    entrant_id: int
    name: str | None = None
    user: UserSummaryPublic | None = None
    team_id: int | None = None
    points: int
    # The best single place, which breaks a tie in points
    best: int | None = None
    legs: list[OverallLeg] = []


class CupOverallPublic(SQLModel):
    """A cup's overall table over its finished rounds, and the points each place pays."""

    points_by_place: list[int] = []
    legs: list[CupLegPublic] = []
    rows: list[OverallRow] = []
