from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import DBModel

if TYPE_CHECKING:
    from app.models.koth_match import DBKothMatch
    from app.models.koth_signup import DBKothSignup


class DBKothMatchParticipant(DBModel):
    __tablename__ = "koth_match_participants"
    __table_args__ = {"mysql_charset": "utf8mb4"}

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("koth_matches.id"))
    signup_id: Mapped[int] = mapped_column(ForeignKey("koth_signups.id"))
    team_number: Mapped[int] = (
        mapped_column()
    )  # Which team this player is on (1, 2, 3, etc.)

    # Relationships
    match: Mapped["DBKothMatch"] = relationship(back_populates="participants")
    signup: Mapped["DBKothSignup"] = relationship(back_populates="match_participations")
