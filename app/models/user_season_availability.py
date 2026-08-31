"""One player's answer for one week of a season: the user_season_availability table.

No row is no answer, and no answer counts as available. The player writes the
row from his dashboard and his captain writes the same row, so the last write
wins and set_by_user_id names whoever wrote it.
"""

from typing import Self

from sqlmodel import Field, SQLModel

from app.models.base import DBModel


class DBUserSeasonAvailability(DBModel, table=True):
    __tablename__ = "user_season_availability"
    user_id: int = Field(foreign_key="users.id", primary_key=True)
    season_id: int = Field(index=True, foreign_key="seasons.id", primary_key=True)
    playday: int = Field(primary_key=True)
    available: bool
    set_by_user_id: int = Field(foreign_key="users.id")


class UserSeasonAvailabilityPublic(SQLModel):
    user_id: int
    playday: int
    available: bool
    set_by_user_id: int
    set_by_name: str | None = None

    @classmethod
    def from_row(cls, row: DBUserSeasonAvailability, set_by_name: str | None) -> Self:
        return cls(
            user_id=row.user_id,
            playday=row.playday,
            available=row.available,
            set_by_user_id=row.set_by_user_id,
            set_by_name=set_by_name,
        )


class AvailabilityWrite(SQLModel):
    """One week's answer. A null clears the row, back to no answer."""

    playday: int
    available: bool | None = None


class PlayerAvailabilityWrite(AvailabilityWrite):
    token: str | None = None
    season_id: int | None = None


class TeamAvailabilityWrite(AvailabilityWrite):
    user_id: int
