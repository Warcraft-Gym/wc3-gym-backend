"""Source identities and evidence for events imported from an archive."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.types import UTCDateTime, utcnow


class HistoricalParticipant(DBModel, table=True):
    __tablename__ = "historical_participant"
    __table_args__ = (UniqueConstraint("event_id", "source_key"),)

    id: int | None = Field(default=None, primary_key=True)
    event_id: int = Field(index=True, foreign_key="event.id", ondelete="CASCADE")
    source_key: str = Field(max_length=200)
    source_name: str = Field(max_length=200)


class KothHistoryEvent(DBModel, table=True):
    __tablename__ = "koth_history_event"

    event_id: int = Field(primary_key=True, foreign_key="event.id", ondelete="CASCADE")
    source_key: str = Field(unique=True, max_length=200)
    source_url: str = Field(max_length=500)
    source_digest: str = Field(max_length=64)
    date_label: str = Field(max_length=200)
    source_record: dict[str, Any] = Field(sa_type=JSON)
    imported_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class KothHistorySeries(DBModel, table=True):
    __tablename__ = "koth_history_series"
    __table_args__ = (UniqueConstraint("event_id", "source_key"),)

    series_id: int = Field(
        primary_key=True, foreign_key="series.id", ondelete="CASCADE"
    )
    event_id: int = Field(index=True, foreign_key="event.id", ondelete="CASCADE")
    source_key: str = Field(max_length=200)
    source_record: dict[str, Any] = Field(sa_type=JSON)
    # Winner-stays-on order names the winner, 1 or 2; shown on the board, never in records
    inferred_winner: int | None = None
    # Why this series stops the bracket's inference, for a human to review
    review_note: str | None = Field(default=None, max_length=200)


class EventVideo(DBModel, table=True):
    __tablename__ = "event_video"
    __table_args__ = (UniqueConstraint("event_id", "provider", "video_key"),)

    id: int | None = Field(default=None, primary_key=True)
    event_id: int = Field(index=True, foreign_key="event.id", ondelete="CASCADE")
    provider: str = Field(max_length=20)
    video_key: str = Field(max_length=100)
    url: str = Field(max_length=500)
    title: str | None = Field(default=None, max_length=500)
    kind: str = Field(default="unknown", max_length=20)
    position: int = 1


class EventVideoPublic(SQLModel):
    id: int
    url: str
    title: str | None = None
    kind: str
