"""Who administers the site.

A row is a grant made on the Config page, and ADMIN_DISCORD_IDS names the
ids that are admin without one. Discord grants nothing: the guild only
mirrors what app.services.admins says.
"""

import os
from datetime import datetime
from typing import Annotated, Literal

from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.types import AwareUTC, NumToStr, UTCDateTime, utcnow


def env_ids() -> set[str]:
    """The Discord ids ADMIN_DISCORD_IDS makes admins without a row."""
    ids = os.getenv("ADMIN_DISCORD_IDS", "").replace(" ", "").split(",")
    return {one for one in ids if one}


class AdminGrantBase(SQLModel):
    # The admin form sends the id as a number, and an id is a snowflake
    discord_id: Annotated[str, NumToStr] = Field(max_length=50, primary_key=True)
    # The display name of the account when the grant was made
    name: str = Field(default="", max_length=50)


class AdminGrant(AdminGrantBase, DBModel, table=True):
    __tablename__ = "admin_grant"

    # The Discord id of the granting account, or "admin" for the token login
    granted_by: str = Field(max_length=50)
    granted_at: Annotated[datetime, AwareUTC] = Field(
        default_factory=utcnow, sa_type=UTCDateTime
    )


class AdminGrantCreate(AdminGrantBase):
    pass


class AdminPublic(AdminGrantBase):
    # An admin from the environment has no row, so it has no grant either
    granted_by: str | None = None
    granted_at: datetime | None = None
    source: Literal["app", "env"]
