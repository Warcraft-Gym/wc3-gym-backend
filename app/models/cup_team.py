"""A team made for one cup: cup_team, its players and its open invitations.

A captain signs the team up and names every other player; each one accepts
before the team counts as whole. The team lives as long as its cup and never
joins a league, so no GNL read (rosters, captains, stats, Discord roles) sees
it. The entrant row of the cup points at it through `cup_team_id`.
"""

from datetime import datetime
from typing import Annotated

from sqlalchemy import false, func
from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.team_summary import TeamSummaryPublic
from app.models.types import AwareUTC, UTCDateTime, utcnow
from app.models.user import UserSummaryPublic


class CupTeam(DBModel, table=True):
    __tablename__ = "cup_team"

    id: int | None = Field(default=None, primary_key=True)
    event_id: int = Field(index=True, foreign_key="event.id", ondelete="CASCADE")
    name: str = Field(max_length=50)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now()},
    )


class CupTeamMember(DBModel, table=True):
    """One confirmed player of a cup team; the captain is one of them."""

    __tablename__ = "cup_team_member"

    team_id: int = Field(
        primary_key=True, foreign_key="cup_team.id", ondelete="CASCADE"
    )
    user_id: int = Field(
        primary_key=True, index=True, foreign_key="users.id", ondelete="CASCADE"
    )
    captain: bool = Field(default=False, sa_column_kwargs={"server_default": false()})


class CupTeamInvite(DBModel, table=True):
    """A player invited into a cup team who has not answered yet: accepting
    makes them a member, declining deletes the row."""

    __tablename__ = "cup_team_invite"

    team_id: int = Field(
        primary_key=True, foreign_key="cup_team.id", ondelete="CASCADE"
    )
    user_id: int = Field(
        primary_key=True, index=True, foreign_key="users.id", ondelete="CASCADE"
    )
    # The cup the team plays, so one statement finds every invite of a cup
    event_id: int = Field(index=True, foreign_key="event.id", ondelete="CASCADE")
    invited_at: Annotated[datetime, AwareUTC] = Field(
        default_factory=utcnow, sa_type=UTCDateTime
    )


def team_summary(team: CupTeam) -> TeamSummaryPublic:
    """A cup team as another object embeds it: its id and its name."""
    return TeamSummaryPublic(id=team.id or 0, name=team.name)


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
