from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship

from app.models.base import DBModel

if TYPE_CHECKING:
    from app.models.koth_match import DBKothMatch
    from app.models.koth_signup import DBKothSignup


class DBKothMatchParticipant(DBModel, table=True):
    __tablename__ = "koth_match_participants"
    __table_args__ = {"mysql_charset": "utf8mb4"}

    id: int | None = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="koth_matches.id")
    signup_id: int = Field(foreign_key="koth_signups.id")
    team_number: int  # Which team this player is on (1, 2, 3, etc.)

    # Relationships
    match: "DBKothMatch" = Relationship(back_populates="participants")
    signup: "DBKothSignup" = Relationship(back_populates="match_participations")
