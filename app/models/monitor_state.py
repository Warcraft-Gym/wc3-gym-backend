"""The last level each monitor check reported, so a check posts an alert once per change."""

from datetime import datetime

from sqlalchemy import Text
from sqlmodel import Field, SQLModel

from app.models.types import UTCDateTime


class MonitorState(SQLModel, table=True):
    __tablename__ = "monitor_state"

    # The check, e.g. egress
    key: str = Field(sa_type=Text, primary_key=True)
    # normal, amber, red or unavailable
    level: str = Field(sa_type=Text)
    # When the check reached this level
    since: datetime = Field(sa_type=UTCDateTime)
    # When a run last wrote the row
    updated_at: datetime = Field(sa_type=UTCDateTime)
