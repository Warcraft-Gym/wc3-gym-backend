"""The shapes the old /koth/* paths still answer with.

The four koth_* tables are gone; `app/services/koth/legacy.py` builds these
payloads from the event model, so the bodies and the responses stay what
Nightbot, the stream overlay and the run crew's bookmarks read before.
"""

from datetime import datetime
from typing import Annotated

from sqlmodel import Field, SQLModel

from app.models.base import PublicModel
from app.models.types import AwareUTC, EnumValue, NoneToList, utcnow


class KothSignupBase(SQLModel):
    event_id: int
    # Optional Twitch username
    twitch_username: str | None = Field(default=None, max_length=50)
    battle_tag: str = Field(max_length=50)  # Can signup multiple times
    w3c_name: str = Field(max_length=50)
    mmr: int  # MMR at time of signup (avg of last 3 seasons)
    bracket: int  # 1, 2, or 3
    is_king: int = 0  # 0=no, 1=yes
    is_active: int = 1  # 0=inactive, 1=active


class KothSignupRequest(SQLModel):
    """The Nightbot signup body. The token rides in the body, so the route
    checks it itself; the Discord bot may also send this shape."""

    client_token: str
    twitch_username: str
    battle_tag: str
    race: str | None = None


class KothSignupAdminRequest(SQLModel):
    """The admin signup body: the admin may leave the Twitch name blank, and
    an empty race list lets the W3C stats pick the best race. The signup lands
    on the event named, or on the active event when none is."""

    twitch_username: str = ""
    battle_tag: str
    races: list[str] = []
    event_id: int | None = None


class KothSignupMeRequest(SQLModel):
    """The signup body of a logged-in player: the battle tag comes from the
    profile, and an empty race list lets the W3C stats pick the best race."""

    races: list[str] = []


class KothBracketUpdate(SQLModel):
    """The bracket body; the service keeps the 1-3 check."""

    bracket: int


class KothSignupPublic(KothSignupBase, PublicModel):
    id: int
    race: Annotated[str | None, EnumValue] = None
    # The flag of the users row with this battle tag, read at answer time
    country: str | None = None


class KothMatchParticipantBase(SQLModel):
    match_id: int
    signup_id: int
    team_number: int  # Which team this player is on (1, 2, 3, etc.)


class KothMatchParticipantPublic(KothMatchParticipantBase):
    id: int
    signup: KothSignupPublic | None = None


class KothMatchBase(SQLModel):
    event_id: int
    bracket: int  # 1, 2, or 3
    # e.g., "1v1", "2v1", "2v2", "3v1", "FFA", "Custom"
    game_mode: str = Field(max_length=50)
    num_teams: int  # Number of teams in the match
    # Team number that won (1, 2, 3, etc.), null until match complete
    winner_team_number: int | None = None


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


class KothMatchResult(SQLModel):
    """The result body: which team won."""

    winner_team_number: int


class KothMatchUpdate(SQLModel):
    event_id: int | None = None
    bracket: int | None = None
    game_mode: str | None = None
    num_teams: int | None = None
    winner_team_number: int | None = None


class KothMatchPublic(KothMatchBase):
    id: int
    participants: Annotated[list[KothMatchParticipantPublic], NoneToList] = []


class KothEventBase(SQLModel):
    name: str = Field(max_length=100)
    description: str | None = Field(default=None, max_length=500)
    event_date: Annotated[datetime, AwareUTC] = Field(default_factory=utcnow)
    is_active: bool = True
    bracket_1_threshold: int = 1450  # < this value
    bracket_2_threshold: int = 1600  # >= bracket_1 and < this value
    # bracket 3 is >= bracket_2_threshold


class KothEventCreate(KothEventBase):
    pass


class KothEventUpdate(SQLModel):
    name: str | None = None
    description: str | None = None
    event_date: Annotated[datetime | None, AwareUTC] = None
    is_active: bool | None = None
    bracket_1_threshold: int | None = None
    bracket_2_threshold: int | None = None


class KothEventSummary(KothEventBase):
    """One row of the events list. The detail routes carry the full tree."""

    id: int


class KothEventPublic(KothEventBase):
    id: int
    event_date: datetime | None = None
    signups: Annotated[list[KothSignupPublic], NoneToList] = []
    matches: Annotated[list[KothMatchPublic], NoneToList] = []
