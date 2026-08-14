from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship

from app.models.base import DBModel

if TYPE_CHECKING:
    from app.models.koth_event import DBKothEvent
    from app.models.koth_match_participant import DBKothMatchParticipant


class DBKothMatch(DBModel, table=True):
    __tablename__ = "koth_matches"
    __table_args__ = {"mysql_charset": "utf8mb4"}

    id: int | None = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="koth_events.id")
    bracket: int  # 1, 2, or 3
    game_mode: str = Field(
        max_length=50
    )  # e.g., "1v1", "2v1", "2v2", "3v1", "FFA", "Custom"
    num_teams: int  # Number of teams in the match
    # Team number that won (1, 2, 3, etc.), null until match complete
    winner_team_number: int | None = None

    # Relationships
    event: "DBKothEvent" = Relationship(back_populates="matches")
    participants: list["DBKothMatchParticipant"] = Relationship(
        back_populates="match",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
