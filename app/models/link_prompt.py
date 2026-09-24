"""What the app asks a login about the accounts it may hold.

A `suggest` row names an earlier player (`person_id`, no login) who may be
the login that holds `tag`, or the login `user_id` names. The login answers
once: accepted joins the player, dismissed closes it. A `taken` row tells
`user_id` that another login verified `tag` on Battle.net and took it.
"""

from datetime import datetime
from typing import Annotated

from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.types import AwareUTC, UTCDateTime, utcnow


class LinkPrompt(DBModel, table=True):
    __tablename__ = "link_prompt"

    id: int | None = Field(default=None, primary_key=True)
    # suggest or taken
    kind: str = Field(max_length=10)
    person_id: int | None = Field(
        default=None, index=True, foreign_key="users.id", ondelete="CASCADE"
    )
    user_id: int | None = Field(
        default=None, index=True, foreign_key="users.id", ondelete="CASCADE"
    )
    tag: str | None = Field(default=None, max_length=50)
    # sheet: the sheet's tag, which a login holds unverified; probable: a
    # name-search guess; discord: the sheet's Discord name; bnet: a verify
    reason: str = Field(max_length=10)
    created_at: Annotated[datetime, AwareUTC] = Field(
        default_factory=utcnow, sa_type=UTCDateTime
    )
    closed_at: Annotated[datetime | None, AwareUTC] = Field(
        default=None, sa_type=UTCDateTime
    )
    # accepted, dismissed, joined or seen
    outcome: str | None = Field(default=None, max_length=10)


class LinkPromptPublic(SQLModel):
    """One open prompt on the login's own profile."""

    id: int
    kind: str
    tag: str | None
    # The earlier player a suggestion names, and the seasons they played
    person_id: int | None = None
    name: str | None = None
    seasons: list[str] = []


class PromptAnswer(SQLModel):
    # True accepts a suggestion; False dismisses it or closes a notice
    accept: bool
