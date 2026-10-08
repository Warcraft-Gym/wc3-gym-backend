"""Who organizes events beside the admins.

An organizer is a Discord account, as an admin is, so it needs no player row.
A grant lets the account create events; an event_organizer row lets it run one
event. A member asks for a grant with a request, and an admin answers it.
"""

from datetime import datetime
from typing import Annotated

from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.types import AwareUTC, NumToStr, UTCDateTime, utcnow


class OrganizerGrant(DBModel, table=True):
    __tablename__ = "organizer_grant"

    discord_id: str = Field(max_length=50, primary_key=True)
    # The display name of the account when the grant was made
    name: str = Field(default="", max_length=50)
    # The Discord id of the granting admin, or "admin" for the token login
    granted_by: str = Field(max_length=50)
    granted_at: Annotated[datetime, AwareUTC] = Field(
        default_factory=utcnow, sa_type=UTCDateTime
    )


class OrganizerRequest(DBModel, table=True):
    """One open request for a grant; an answer deletes it."""

    __tablename__ = "organizer_request"

    discord_id: str = Field(max_length=50, primary_key=True)
    name: str = Field(default="", max_length=50)
    # What the member wants to run, in their own words
    note: str | None = Field(default=None, max_length=300)
    requested_at: Annotated[datetime, AwareUTC] = Field(
        default_factory=utcnow, sa_type=UTCDateTime
    )


class EventOrganizer(DBModel, table=True):
    """One account that runs one event: its creator, or a co-organizer."""

    __tablename__ = "event_organizer"

    event_id: int = Field(foreign_key="event.id", ondelete="CASCADE", primary_key=True)
    discord_id: str = Field(max_length=50, primary_key=True, index=True)
    name: str = Field(default="", max_length=50)
    # The Discord id of whoever added the row, or "admin" for the token login
    added_by: str = Field(max_length=50)
    added_at: Annotated[datetime, AwareUTC] = Field(
        default_factory=utcnow, sa_type=UTCDateTime
    )


class OrganizerGrantCreate(SQLModel):
    # The admin form sends the id as a number, and an id is a snowflake
    discord_id: Annotated[str, NumToStr] = Field(max_length=50)
    name: str = Field(default="", max_length=50)


class OrganizerRequestCreate(SQLModel):
    note: str | None = Field(default=None, max_length=300)


class OrganizerPublic(SQLModel):
    discord_id: str
    name: str
    granted_by: str
    granted_at: Annotated[datetime, AwareUTC]
    # The events this account runs, closed ones included
    events: int = 0


class OrganizerRequestPublic(SQLModel):
    discord_id: str
    name: str
    note: str | None = None
    requested_at: Annotated[datetime, AwareUTC]
    # The player row behind the account, when it has one
    user_id: int | None = None


class EventOrganizerWrite(SQLModel):
    discord_id: Annotated[str, NumToStr] = Field(max_length=50)
    name: str = Field(default="", max_length=50)


class EventOrganizerPublic(SQLModel):
    discord_id: str
    name: str
    added_by: str
    added_at: Annotated[datetime, AwareUTC]
