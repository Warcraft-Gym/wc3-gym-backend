from datetime import datetime
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship

from app.models.base import DBModel

if TYPE_CHECKING:
    from app.models.koth_match import DBKothMatch
    from app.models.koth_signup import DBKothSignup


class DBKothEvent(DBModel, table=True):
    __tablename__ = "koth_events"
    __table_args__ = {"mysql_charset": "utf8mb4"}

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    description: str | None = Field(default=None, max_length=500)
    event_date: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True
    bracket_1_threshold: int = 1450  # < this value
    bracket_2_threshold: int = 1600  # >= bracket_1 and < this value
    # bracket 3 is >= bracket_2_threshold

    # Relationships
    signups: list["DBKothSignup"] = Relationship(
        back_populates="event",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    matches: list["DBKothMatch"] = Relationship(
        back_populates="event",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
