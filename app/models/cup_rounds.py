"""A cup played over several rounds: its legs, their stages and their check-ins.

A cup made with rounds plays each round as a competition of its own, a leg,
on its own date, with its own copy of the cup's stages and the players
checked in for it. Each leg's places pay points from the cup's points table
(`cup_settings.points_by_place`), and the overall table adds them up. The
backend says leg, because `event_round` is a column of a bracket; the screens
say round. Every row here is a cup's, so no GNL or KOTH read sees one.
"""

from datetime import datetime
from typing import Annotated

from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.types import AwareUTC, UTCDateTime


class CupLeg(DBModel, table=True):
    __tablename__ = "cup_leg"

    id: int | None = Field(default=None, primary_key=True)
    event_id: int = Field(index=True, foreign_key="event.id", ondelete="CASCADE")
    # The rounds of a cup count from 1, in the order they are played
    number: int
    name: str | None = Field(default=None, max_length=50)
    starts_at: Annotated[datetime | None, AwareUTC] = Field(
        default=None, sa_type=UTCDateTime
    )
    # When a runner finished the round; its places count from then on
    finished_at: Annotated[datetime | None, AwareUTC] = Field(
        default=None, sa_type=UTCDateTime
    )


class CupLegStage(DBModel, table=True):
    """Which leg a stage of the cup is played in."""

    __tablename__ = "cup_leg_stage"

    stage_id: int = Field(
        primary_key=True, foreign_key="event_stage.id", ondelete="CASCADE"
    )
    leg_id: int = Field(index=True, foreign_key="cup_leg.id", ondelete="CASCADE")


class CupLegCheckin(DBModel, table=True):
    """A player who plays one round: the leg's draw takes these alone."""

    __tablename__ = "cup_leg_checkin"

    leg_id: int = Field(primary_key=True, foreign_key="cup_leg.id", ondelete="CASCADE")
    entrant_id: int = Field(
        primary_key=True, foreign_key="event_entrant.id", ondelete="CASCADE"
    )
    checked_in_at: Annotated[datetime, AwareUTC] = Field(sa_type=UTCDateTime)


class CupLegWrite(SQLModel):
    """One round of a new cup: when it starts, and a name if it has one."""

    starts_at: Annotated[datetime | None, AwareUTC] = None
    name: str | None = Field(default=None, max_length=50)


class CupLegUpdate(SQLModel):
    """A round's change after creation; a field left out keeps its value, and a
    name sent empty goes back to "Round n"."""

    name: str | None = Field(default=None, max_length=50)
    starts_at: Annotated[datetime | None, AwareUTC] = None


class CupLegPublic(SQLModel):
    """One round as the cup's pages read it."""

    id: int
    number: int
    name: str | None = None
    starts_at: Annotated[datetime | None, AwareUTC] = None
    finished_at: Annotated[datetime | None, AwareUTC] = None
    # The cup's stages this round plays, in play order
    stage_ids: list[int] = []
    # The entrants checked in for it
    checked_in: list[int] = []
    # When a player's own check-in for the round opens; null when it is open from sign-up
    checkin_opens_at: Annotated[datetime | None, AwareUTC] = None
    # When it closes early; null when it closes at the round's draw
    checkin_closes_at: Annotated[datetime | None, AwareUTC] = None


class CupLegCheckinWrite(SQLModel):
    """A check-in for one round: the caller's own, or a runner's for an entrant."""

    entrant_id: int | None = None
