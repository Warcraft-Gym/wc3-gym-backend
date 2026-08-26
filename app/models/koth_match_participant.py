from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.koth_signup import KothSignupPublic

if TYPE_CHECKING:
    from app.models.koth_match import KothMatch
    from app.models.koth_signup import KothSignup


class KothMatchParticipantBase(SQLModel):
    match_id: int = Field(foreign_key="koth_matches.id")
    signup_id: int = Field(foreign_key="koth_signups.id")
    team_number: int  # Which team this player is on (1, 2, 3, etc.)


class KothMatchParticipant(KothMatchParticipantBase, DBModel, table=True):
    __tablename__ = "koth_match_participants"

    id: int | None = Field(default=None, primary_key=True)

    # Relationships
    match: "KothMatch" = Relationship(back_populates="participants")
    signup: "KothSignup" = Relationship(back_populates="match_participations")


class KothMatchParticipantCreate(KothMatchParticipantBase):
    pass


class KothMatchParticipantPublic(KothMatchParticipantBase):
    id: int
    signup: KothSignupPublic | None = None
