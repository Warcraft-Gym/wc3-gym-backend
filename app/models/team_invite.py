"""A pending invitation into the team a captain signed up for one cup.

The roster of a team (user_team_season) holds confirmed players only: an
invited player stands here until they accept, which moves them into the
roster, or decline, which deletes the row.
"""

from datetime import datetime
from typing import Annotated

from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.team_summary import TeamSummaryPublic
from app.models.types import AwareUTC, UTCDateTime, utcnow
from app.models.user import UserSummaryPublic


class TeamInvite(DBModel, table=True):
    __tablename__ = "team_invite"

    team_id: int = Field(primary_key=True, foreign_key="teams.id", ondelete="CASCADE")
    user_id: int = Field(
        primary_key=True, index=True, foreign_key="users.id", ondelete="CASCADE"
    )
    # The cup the team plays, so one statement finds every invite of a cup
    event_id: int = Field(index=True, foreign_key="event.id", ondelete="CASCADE")
    invited_at: Annotated[datetime, AwareUTC] = Field(
        default_factory=utcnow, sa_type=UTCDateTime
    )


class TeamInviteCreate(SQLModel):
    """One more player a captain invites into the team."""

    user_id: int


class CupTeamCreate(SQLModel):
    """A team a captain signs up for a cup: its name and every other player."""

    name: str = Field(min_length=1, max_length=50)
    member_ids: list[int]


class CupTeamAdd(CupTeamCreate):
    """A team an event's runner enters by hand: its captain and players, all confirmed."""

    captain_id: int


class MemberReplace(SQLModel):
    """The player who takes another's place in a team."""

    user_id: int


class TeamInvitePublic(SQLModel):
    """An invitation as the invited player reads it: the team, the captain, the cup."""

    event_id: int
    event_name: str | None = None
    team: TeamSummaryPublic
    captain: UserSummaryPublic | None = None
    invited_at: Annotated[datetime | None, AwareUTC] = None
