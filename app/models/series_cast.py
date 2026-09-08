"""A member's claim to cast one series: the series_cast table.

A row names the series, the account that claimed it and the channel it streams on.
An imported or admin-entered cast has no account. Planned, live and VOD are never
stored: they derive at read time from the series result and the row's VOD.
"""

import re
from datetime import datetime
from typing import Self
from urllib.parse import urlsplit

from pydantic import field_validator
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel, PublicModel, ident
from app.models.types import UTCDateTime, utcnow
from app.models.user import User

STREAM_HOSTS = {"twitch.tv", "youtube.com", "youtu.be"}


def _host_path(value: str) -> tuple[str, str, str]:
    """The URL with its scheme, its host without www or m, and its path."""
    value = value.strip()
    if not re.match(r"https?://", value, re.IGNORECASE):
        value = f"https://{value}"
    parts = urlsplit(value)
    host = re.sub(r"^(www|m)\.", "", parts.hostname or "")
    return value, host, parts.path.rstrip("/")


def channel_url(value: str) -> str:
    """The URL with its scheme, or a ValueError when it is not a Twitch or YouTube link."""
    value, host, path = _host_path(value)
    if host not in STREAM_HOSTS or not path:
        raise ValueError("A twitch.tv, youtube.com or youtu.be link is needed")
    return value


# A Twitch video, a YouTube watch or live page, or a youtu.be short link
VOD_PATHS = {
    "twitch.tv": r"/videos/\d+",
    "youtube.com": r"/watch|/live/[\w-]+",
    "youtu.be": r"/[\w-]+",
}


def vod_url(value: str) -> str:
    """The video URL with its scheme, or a ValueError. A `?t=` start stays."""
    value, host, path = _host_path(value)
    if host not in VOD_PATHS or not re.fullmatch(VOD_PATHS[host], path):
        raise ValueError(
            "A twitch.tv/videos, youtube.com/watch, youtube.com/live or youtu.be link is needed"
        )
    return value


def channel_name(url: str) -> str:
    """What a chip shows for a cast with no account: the link without its scheme."""
    return re.sub(r"^https?://(www\.)?", "", url).rstrip("/")


class SeriesCast(DBModel, table=True):
    __tablename__ = "series_cast"
    # One claim per account and series; imported casts have no account
    __table_args__ = (UniqueConstraint("series_id", "user_id"),)

    id: int | None = Field(default=None, primary_key=True)
    series_id: int = Field(index=True, foreign_key="series.id", ondelete="CASCADE")
    user_id: int | None = Field(
        default=None, foreign_key="users.id", ondelete="SET NULL"
    )
    channel_url: str = Field(max_length=200)
    vod_url: str | None = Field(default=None, max_length=300)
    # Kept because a Twitch VOD expires
    vod_added_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    created_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)

    user: User | None = Relationship()


class CastWrite(SQLModel):
    channel_url: str = Field(max_length=200)

    @field_validator("channel_url")
    @classmethod
    def _stream_link(cls, value: str) -> str:
        return channel_url(value)


class VodWrite(SQLModel):
    # None clears the VOD
    vod_url: str | None = Field(default=None, max_length=300)

    @field_validator("vod_url")
    @classmethod
    def _video_link(cls, value: str | None) -> str | None:
        return vod_url(value) if value else None


class ClaimWrite(CastWrite, VodWrite):
    """A claim. A series that is over is claimed with its VOD, which is also the channel."""


class CastPublic(PublicModel):
    id: int
    series_id: int
    user_id: int | None = None
    # The account's name, or the channel for a cast with no account
    name: str
    channel_url: str
    vod_url: str | None = None
    vod_added_at: datetime | None = None
    created_at: datetime

    @classmethod
    def from_cast(cls, cast: SeriesCast) -> Self:
        return cls(
            id=ident(cast),
            series_id=cast.series_id,
            user_id=cast.user_id,
            name=cast.user.name if cast.user else channel_name(cast.channel_url),
            channel_url=cast.channel_url,
            vod_url=cast.vod_url,
            vod_added_at=cast.vod_added_at,
            created_at=cast.created_at,
        )
