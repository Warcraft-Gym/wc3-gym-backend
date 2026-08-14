from typing import TYPE_CHECKING, Annotated

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.enums import Race
from app.models.types import EnumValue

if TYPE_CHECKING:
    from app.models.koth_event import KothEvent
    from app.models.koth_match_participant import KothMatchParticipant


class KothSignupBase(SQLModel):
    event_id: int = Field(foreign_key="koth_events.id")
    # Optional Twitch username
    twitch_username: str | None = Field(default=None, max_length=50)
    battle_tag: str = Field(max_length=50)  # Can signup multiple times
    w3c_name: str = Field(max_length=50)
    mmr: int  # MMR at time of signup (avg of last 3 seasons)
    bracket: int  # 1, 2, or 3
    is_king: int = 0  # 0=no, 1=yes
    is_active: int = 1  # 0=inactive, 1=active


class KothSignup(KothSignupBase, DBModel, table=True):
    __tablename__ = "koth_signups"
    __table_args__ = {"mysql_charset": "utf8mb4"}

    id: int | None = Field(default=None, primary_key=True)
    race: Race

    # Relationships
    event: "KothEvent" = Relationship(back_populates="signups")
    match_participations: list["KothMatchParticipant"] = Relationship(
        back_populates="signup",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class KothSignupCreate(KothSignupBase):
    # A Race member from the w3champions sync, a plain string from a
    # Nightbot command.
    race: Race | str


class KothSignupUpdate(SQLModel):
    event_id: int | None = None
    twitch_username: str | None = None
    battle_tag: str | None = None
    w3c_name: str | None = None
    race: Race | str | None = None
    mmr: int | None = None
    bracket: int | None = None
    is_king: int | None = None
    is_active: int | None = None


class KothSignupPublic(KothSignupBase):
    id: int
    race: Annotated[str | None, EnumValue] = None

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")
