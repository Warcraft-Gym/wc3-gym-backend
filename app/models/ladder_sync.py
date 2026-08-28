"""What the ladder sync has already read.

w3champions serves matches per player and per w3champions season, so that
pair is the unit a sync finishes. One row says the pair was read, when, and
whether the walk reached the end of the season. A closed season read to its
end is never asked for again; the open one is re-read from its own stamp.
"""

from datetime import datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from app.models.base import DBModel


class LadderSyncBase(SQLModel):
    user_id: int = Field(foreign_key="users.id")
    wc3_season: int
    # UTC without a zone, the shape the DATETIME columns hold
    synced_at: datetime
    # The season was paged to its end, or past the window it was read for
    complete: bool = False


class LadderSync(LadderSyncBase, DBModel, table=True):
    __tablename__ = "ladder_sync"
    # One row per player per w3champions season
    __table_args__ = (
        Index("uq_ladder_sync_user_season", "user_id", "wc3_season", unique=True),
    )

    id: int | None = Field(default=None, primary_key=True)
