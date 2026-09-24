"""The battle tags a person has played under.

A person holds many tags and a tag belongs to at most one person. The active
row is the account the sites show; users.battleTag holds a copy of its tag.
"""

from datetime import datetime
from typing import Annotated

from sqlalchemy import Index, text
from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.types import AwareUTC, UTCDateTime, utcnow


class UserBattleTagBase(SQLModel):
    tag: str = Field(max_length=50)
    # The Battle.net account behind the tag, set only by a Battle.net link
    bnet_account_id: str | None = Field(default=None, max_length=50)
    # How the tag reached the person: sheet, signup, claim, admin or link
    source: str = Field(max_length=10)
    is_active: bool = False
    first_seen: Annotated[datetime, AwareUTC] = Field(
        default_factory=utcnow, sa_type=UTCDateTime
    )
    last_seen: Annotated[datetime, AwareUTC] = Field(
        default_factory=utcnow, sa_type=UTCDateTime
    )


class UserBattleTag(UserBattleTagBase, DBModel, table=True):
    __tablename__ = "user_battle_tag"
    # A tag names one person, whatever its case; a person has one active tag
    __table_args__ = (
        Index("uq_user_battle_tag_tag", text("lower(trim(tag))"), unique=True),
        Index(
            "uq_user_battle_tag_active_user",
            "user_id",
            unique=True,
            sqlite_where=text("is_active"),
            postgresql_where=text("is_active"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id", ondelete="CASCADE")
