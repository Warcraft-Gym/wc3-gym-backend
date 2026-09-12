"""A league: the thing that repeats. Each run of it is one event.

The GNL is one league and its seasons are its events; KOTH is another.
A league carries no defaults for its events (NE-4): it is a name, a short
name, who enters, and an optional page link.
"""

from datetime import datetime
from typing import Annotated

from sqlalchemy import func
from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.enums import EntrantKind
from app.models.types import NumToStr, UTCDateTime, utcnow


class LeagueBase(SQLModel):
    name: Annotated[str, NumToStr] = Field(max_length=100, unique=True)
    short_name: Annotated[str | None, NumToStr] = Field(default=None, max_length=20)
    # The rules or landing page of the league, shown as one "Page" link
    page_url: str | None = Field(default=None, max_length=500)
    entrant_kind: EntrantKind = Field(
        default=EntrantKind.solo, sa_column_kwargs={"server_default": "solo"}
    )


class League(LeagueBase, DBModel, table=True):
    __tablename__ = "league"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now()},
    )


class LeaguePublic(LeagueBase):
    id: int
