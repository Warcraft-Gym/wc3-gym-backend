"""One entrant of an event: a player, or a pre-made team.

Eligibility warns and never blocks (NE-8), so nothing here refuses a signup:
a withdrawn or unchecked-in entrant keeps its row and its stamps say so. The
one thing the row does refuse is naming both a user and a team, or neither.
"""

from datetime import datetime
from typing import Annotated

from sqlalchemy import CheckConstraint, UniqueConstraint, false, func
from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.enums import Race, SeedSource, SignupChannel
from app.models.team_reduced import TeamReduced
from app.models.types import (
    AwareUTC,
    EnumValue,
    NumToStr,
    SuggestRace,
    UTCDateTime,
    utcnow,
)
from app.models.user import UserPublic


class EventEntrant(DBModel, table=True):
    __tablename__ = "event_entrant"
    __table_args__ = (
        # An event that takes one entry per race holds a row per race
        UniqueConstraint(
            "event_id",
            "user_id",
            "race",
            name="uq_event_entrant_event_id_user_id_race",
        ),
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
    # A player enters on a race; a team enters on the races of its roster
    race: Annotated[Race | None, SuggestRace] = None
    # What the entrant wants to work on, which a signup-only event asks for
    note: str | None = Field(default=None, max_length=200)
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
    # The group of a group stage, written by generate and cleared by advance
    group_no: int | None = None
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


class EntrantSignup(SQLModel):
    """A player or a team entering an event through the signup routes."""

    # A player names the race; a team has none, and the service refuses a
    # player row without one
    race: Annotated[Race | None, SuggestRace] = None
    note: str | None = Field(default=None, max_length=200)
    # An `anyone` event takes a battle tag where a `members` event takes the session
    battle_tag: Annotated[str | None, NumToStr] = None
    # A team entrant names its team; the caller captains it, or is an admin
    team_id: int | None = None
    channel: SignupChannel = SignupChannel.web


class EntrantAdd(EntrantSignup):
    """The admin form, which may name any player instead of the caller."""

    user_id: int | None = None


class EntrantPlacement(SQLModel):
    """An admin moving one entrant into a division; the move is placement by hand."""

    division_id: int | None = None
    manual_placement: bool = True


class SeedWrite(SQLModel):
    """What orders the seeds of one stage; `order` names the entrants by hand."""

    source: SeedSource = SeedSource.mmr
    order: list[int] | None = None


class EventEntrantPublic(SQLModel):
    """One entrant as the entrants page reads it.

    The warnings say what an admin should look at; none of them refused the
    signup. The MMR is the W3C rating of the race the entrant signed up on,
    stamped with the time the app last read that player from w3champions.
    """

    id: int
    event_id: int
    user: UserPublic | None = None
    team: TeamReduced | None = None
    race: Annotated[str | None, EnumValue] = None
    note: str | None = None
    channel: Annotated[str | None, EnumValue] = None
    mmr: int | None = None
    mmr_synced_at: datetime | None = None
    warnings: list[str] = []
    seed: int | None = None
    seed_source: str | None = None
    mmr_at_seed: int | None = None
    division_id: int | None = None
    group_no: int | None = None
    manual_placement: bool = False
    checked_in_at: Annotated[datetime | None, AwareUTC] = None
    withdrawn_at: Annotated[datetime | None, AwareUTC] = None
    qualified_from_event_id: int | None = None
