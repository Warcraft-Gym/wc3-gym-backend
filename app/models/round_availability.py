"""One player's answer for one round of an event: the round_availability table.

No row is no answer, and no answer counts as available. The player writes the
row from the dashboard and their captain writes the same row, so the last
write wins and set_by_user_id names whoever wrote it.

C1 renamed the table and added round_id beside the season and the playday;
the older pair is dropped a deploy later, once every reader keys on the round.
"""

from typing import Self

from sqlmodel import Field, SQLModel

from app.models.base import DBModel


class DBRoundAvailability(DBModel, table=True):
    __tablename__ = "round_availability"
    user_id: int = Field(foreign_key="users.id", primary_key=True)
    season_id: int = Field(index=True, foreign_key="event.id", primary_key=True)
    playday: int = Field(primary_key=True)
    # The round the answer is about; C2 makes it the key and refuses a null
    round_id: int | None = Field(default=None, index=True, foreign_key="event_round.id")
    available: bool
    set_by_user_id: int = Field(foreign_key="users.id")


class RoundAvailabilityPublic(SQLModel):
    user_id: int
    playday: int
    available: bool
    set_by_user_id: int
    set_by_name: str | None = None

    @classmethod
    def from_row(cls, row: DBRoundAvailability, set_by_name: str | None) -> Self:
        return cls(
            user_id=row.user_id,
            playday=row.playday,
            available=row.available,
            set_by_user_id=row.set_by_user_id,
            set_by_name=set_by_name,
        )


class AvailabilityWrite(SQLModel):
    """One round's answer. A null clears the row, back to no answer."""

    playday: int
    available: bool | None = None


class PlayerAvailabilityWrite(AvailabilityWrite):
    season_id: int | None = None


class TeamAvailabilityWrite(AvailabilityWrite):
    user_id: int
