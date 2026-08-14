from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import DBModel
from app.models.enums import Race

if TYPE_CHECKING:
    from app.models.koth_event import DBKothEvent
    from app.models.koth_match_participant import DBKothMatchParticipant


class DBKothSignup(DBModel):
    __tablename__ = "koth_signups"
    __table_args__ = {"mysql_charset": "utf8mb4"}

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("koth_events.id"))
    twitch_username: Mapped[str | None] = mapped_column(
        String(50)
    )  # Optional Twitch username
    battle_tag: Mapped[str] = mapped_column(String(50))  # Can signup multiple times
    w3c_name: Mapped[str] = mapped_column(String(50))
    race: Mapped[Race] = mapped_column(Enum(Race))
    mmr: Mapped[int] = mapped_column()  # MMR at time of signup (avg of last 3 seasons)
    bracket: Mapped[int] = mapped_column()  # 1, 2, or 3
    is_king: Mapped[int] = mapped_column(default=0)  # 0=no, 1=yes
    is_active: Mapped[int] = mapped_column(default=1)  # 0=inactive, 1=active

    # Relationships
    event: Mapped["DBKothEvent"] = relationship(back_populates="signups")
    match_participations: Mapped[list["DBKothMatchParticipant"]] = relationship(
        back_populates="signup", cascade="all, delete-orphan"
    )
