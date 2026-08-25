from typing import TYPE_CHECKING, Annotated

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.koth_match_participant import KothMatchParticipantPublic
from app.models.types import NoneToList

if TYPE_CHECKING:
    from app.models.koth_event import KothEvent
    from app.models.koth_match_participant import KothMatchParticipant


class KothMatchBase(SQLModel):
    event_id: int = Field(foreign_key="koth_events.id")
    bracket: int  # 1, 2, or 3
    # e.g., "1v1", "2v1", "2v2", "3v1", "FFA", "Custom"
    game_mode: str = Field(max_length=50)
    num_teams: int  # Number of teams in the match
    # Team number that won (1, 2, 3, etc.), null until match complete
    winner_team_number: int | None = None


class KothMatch(KothMatchBase, DBModel, table=True):
    __tablename__ = "koth_matches"
    __table_args__ = {"mysql_charset": "utf8mb4"}

    id: int | None = Field(default=None, primary_key=True)

    # Relationships
    event: "KothEvent" = Relationship(back_populates="matches")
    participants: list["KothMatchParticipant"] = Relationship(
        back_populates="match",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class KothMatchCreate(KothMatchBase):
    # create_match derives this from the participants
    bracket: int | None = None


class KothMatchParticipantRef(SQLModel):
    """One entry of the participants list a create-match request carries."""

    signup_id: int
    team_number: int


class KothMatchCreateRequest(KothMatchCreate):
    """The create-match body: the match, plus who plays in it."""

    participants: list[KothMatchParticipantRef] = []


class KothMatchUpdate(SQLModel):
    event_id: int | None = None
    bracket: int | None = None
    game_mode: str | None = None
    num_teams: int | None = None
    winner_team_number: int | None = None


class KothMatchPublic(KothMatchBase):
    id: int
    participants: Annotated[list[KothMatchParticipantPublic], NoneToList] = []
