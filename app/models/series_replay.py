"""The replay of one game: the series_replay table.

A series has one replay slot per game. A player uploads it with the result,
and a later upload replaces the earlier one. The file itself lives in the R2
bucket; a row holds its object key and who uploaded it when.
"""

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.types import UTCDateTime, utcnow


class DBSeriesReplay(DBModel, table=True):
    __tablename__ = "series_replay"
    series_id: int = Field(
        foreign_key="series.id", ondelete="CASCADE", primary_key=True
    )
    # The games count from 1, in the order they were played
    game_no: int = Field(primary_key=True)
    key: str = Field(max_length=500)
    uploaded_by: int | None = Field(
        default=None, foreign_key="users.id", ondelete="SET NULL"
    )
    uploaded_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class SeriesReplayPublic(SQLModel):
    series_id: int
    game_no: int
    url: str
    uploaded_by: int | None = None
    uploaded_at: datetime
