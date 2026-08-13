from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import DBModel

if TYPE_CHECKING:
    from src.models.koth_event import DBKothEvent
    from src.models.koth_match_participant import DBKothMatchParticipant


class DBKothMatch(DBModel):
    __tablename__ = "koth_matches"
    __table_args__ = {"mysql_charset": "utf8mb4"}

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("koth_events.id"))
    bracket: Mapped[int] = mapped_column()  # 1, 2, or 3
    game_mode: Mapped[str] = mapped_column(
        String(50)
    )  # e.g., "1v1", "2v1", "2v2", "3v1", "FFA", "Custom"
    num_teams: Mapped[int] = mapped_column()  # Number of teams in the match
    winner_team_number: Mapped[int | None] = (
        mapped_column()
    )  # Team number that won (1, 2, 3, etc.), null until match complete

    # Relationships
    event: Mapped["DBKothEvent"] = relationship(back_populates="matches")
    participants: Mapped[list["DBKothMatchParticipant"]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )
