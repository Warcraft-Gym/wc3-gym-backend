"""What the captains keep beside the pairings of one fixture.

`match_draft_mark` holds one row per team: the advisory Ready mark and the
moment that team last read the pairings. `match_draft_state` holds one row per
fixture: the working largest MMR difference the captains pair inside, which
stands in front of the stage setting until it is cleared.
"""

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.types import UTCDateTime


class DBMatchDraftMark(DBModel, table=True):
    __tablename__ = "match_draft_mark"

    match_id: int = Field(
        foreign_key="matches.id", ondelete="CASCADE", primary_key=True
    )
    team_id: int = Field(foreign_key="teams.id", ondelete="CASCADE", primary_key=True)
    # Who marked the team ready; cleared whenever a pairing of the fixture changes
    ready_by_user_id: int | None = Field(
        default=None, foreign_key="users.id", ondelete="SET NULL"
    )
    ready_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    # When the team last read the pairings, so the page can mark later edits
    seen_at: datetime | None = Field(default=None, sa_type=UTCDateTime)


class DBMatchDraftState(DBModel, table=True):
    __tablename__ = "match_draft_state"

    match_id: int = Field(
        foreign_key="matches.id", ondelete="CASCADE", primary_key=True
    )
    # The working largest MMR difference; null reads the stage setting
    max_mmr_difference: int | None = None


class MatchDraftTeamMark(SQLModel):
    """One team's Ready mark; both teams of the fixture are answered."""

    team_id: int
    ready_by_user_id: int | None = None
    ready_by_name: str | None = None
    ready_at: datetime | None = None


class MatchDraftStatePublic(SQLModel):
    """The marks and the working values of one fixture's draft. No rows."""

    match_id: int
    # What the captains pair inside today: the working value, else the stage one
    max_mmr_difference: int | None = None
    # What the stage names; a gnl stage that sets none reads 100
    stage_max_mmr_difference: int | None = None
    teams: list[MatchDraftTeamMark] = []
    # When the caller's own team last read the pairings; null for an admin
    seen_at: datetime | None = None


class ReadyWrite(SQLModel):
    """Set or clear one team's Ready mark."""

    ready: bool


class MaxMmrDifferenceWrite(SQLModel):
    """The working value of the fixture; null puts it back on the stage one."""

    max_mmr_difference: int | None = Field(default=None, ge=1)


class ReplacePreviewPublic(SQLModel):
    """What promoting a replacing draft takes away with the published series."""

    series_id: int
    # The booked time the replace loses, and whether a veto board exists
    date_time: datetime | None = None
    has_veto: bool = False
    has_result: bool = False
    has_replay: bool = False
