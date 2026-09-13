"""One entrant of an event: a player, or a pre-made team.

Eligibility warns and never blocks (NE-8), so nothing here refuses a signup:
a withdrawn or unchecked-in entrant keeps its row and its stamps say so. The
one thing the row does refuse is naming both a user and a team, or neither.
"""

from datetime import datetime
from typing import Annotated

from sqlalchemy import CheckConstraint, UniqueConstraint, false, func
from sqlmodel import Field

from app.models.base import DBModel
from app.models.enums import Race, SignupChannel
from app.models.types import AwareUTC, SuggestRace, UTCDateTime, utcnow


class EventEntrant(DBModel, table=True):
    __tablename__ = "event_entrant"
    __table_args__ = (
        UniqueConstraint("event_id", "user_id"),
        UniqueConstraint(
            "event_id", "team_id", name="uq_event_entrant_event_id_team_id"
        ),
        # A row is one side: a player or a team, never both and never neither
        CheckConstraint(
            "(CASE WHEN user_id IS NULL THEN 0 ELSE 1 END "
            "+ CASE WHEN team_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="one_entrant",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    event_id: int = Field(index=True, foreign_key="event.id", ondelete="CASCADE")
    user_id: int | None = Field(
        default=None, index=True, foreign_key="users.id", ondelete="CASCADE"
    )
    # A team event enters pre-made teams; exactly one of the two columns is set
    team_id: int | None = Field(
        default=None, index=True, foreign_key="teams.id", ondelete="CASCADE"
    )
    race: Annotated[Race, SuggestRace]
    # Where the stage seeds this entrant; null until the seeds are set
    seed: int | None = None
    # The MMR the seed was cut from, and the source that cut it
    mmr_at_seed: int | None = None
    seed_source: str | None = Field(default=None, max_length=20)
    # On: an admin placed this entrant by hand, so a reseed leaves it alone
    manual_placement: bool = Field(
        default=False, sa_column_kwargs={"server_default": false()}
    )
    division_id: int | None = Field(
        default=None, foreign_key="event_division.id", ondelete="SET NULL"
    )
    # The qualifier this entrant came through; null for a direct signup
    qualified_from_event_id: int | None = Field(
        default=None, foreign_key="event.id", ondelete="SET NULL"
    )
    channel: SignupChannel = Field(
        default=SignupChannel.web, sa_column_kwargs={"server_default": "web"}
    )
    checked_in_at: Annotated[datetime | None, AwareUTC] = Field(
        default=None, sa_type=UTCDateTime
    )
    withdrawn_at: Annotated[datetime | None, AwareUTC] = Field(
        default=None, sa_type=UTCDateTime
    )
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now()},
    )
