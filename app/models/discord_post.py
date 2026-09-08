"""A message the bot posted that the app keeps true: the discord_post table.

A row names the post (channel and message id), the card it shows (kind) and
the row the card is about (subject_id: the series of a veto or announce
card). A write to the subject edits every post of it, so a card stays true
in every channel it was posted in. The core tables carry no bot state.
"""

from datetime import datetime

from sqlalchemy import Index
from sqlmodel import Field

from app.models.base import DBModel
from app.models.types import UTCDateTime


class DiscordPost(DBModel, table=True):
    __tablename__ = "discord_post"
    __table_args__ = (Index("ix_discord_post_kind_subject_id", "kind", "subject_id"),)

    id: int | None = Field(default=None, primary_key=True)
    # The command that built the card: veto, announce
    kind: str = Field(max_length=16)
    subject_id: int
    channel_id: str = Field(max_length=20)
    message_id: str = Field(max_length=20, unique=True)
    # When the subject last changed, and when the card was last edited for it
    changed_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    edited_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
