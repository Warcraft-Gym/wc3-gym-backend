from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship

from app.models.base import DBModel
from app.models.enums import Race

if TYPE_CHECKING:
    from app.models.koth_event import DBKothEvent
    from app.models.koth_match_participant import DBKothMatchParticipant


class DBKothSignup(DBModel, table=True):
    __tablename__ = "koth_signups"
    __table_args__ = {"mysql_charset": "utf8mb4"}

    id: int | None = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="koth_events.id")
    # Optional Twitch username
    twitch_username: str | None = Field(default=None, max_length=50)
    battle_tag: str = Field(max_length=50)  # Can signup multiple times
    w3c_name: str = Field(max_length=50)
    race: Race
    mmr: int  # MMR at time of signup (avg of last 3 seasons)
    bracket: int  # 1, 2, or 3
    is_king: int = 0  # 0=no, 1=yes
    is_active: int = 1  # 0=inactive, 1=active

    # Relationships
    event: "DBKothEvent" = Relationship(back_populates="signups")
    match_participations: list["DBKothMatchParticipant"] = Relationship(
        back_populates="signup",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
