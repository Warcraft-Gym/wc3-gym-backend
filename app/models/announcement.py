"""Who takes the cup announcements, and what the Home switch reads.

A member joins or leaves the announcement role on Home. The row records the
choice by the Discord account, which is what the role is granted to; the
guild's role follows it through the bot.
"""

from datetime import datetime

from sqlalchemy import func
from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.types import UTCDateTime, utcnow


class AnnouncementSubscriber(DBModel, table=True):
    __tablename__ = "announcement_subscriber"

    discord_id: str = Field(max_length=50, primary_key=True)
    subscribed_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now()},
    )


class AnnouncementState(SQLModel):
    """The Home switch: whether it shows, and where it stands."""

    # The channel and the role are set and the caller is a guild member
    available: bool
    # The caller takes the announcement role
    subscribed: bool


class AnnouncementWrite(SQLModel):
    subscribed: bool
