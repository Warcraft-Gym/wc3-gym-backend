"""The login request body."""

from typing import Annotated

from sqlmodel import SQLModel

from app.models.types import NumToStr


class LoginRequest(SQLModel):
    token: str


class PublicAccessRequest(SQLModel):
    """The bot's ask for a one-time public URL.

    Every field also arrives as a query param, which the body wins over.
    The bot sends the season id and the ttl as text or as numbers.
    """

    client_token: Annotated[str | None, NumToStr] = None
    discord_id: Annotated[str | None, NumToStr] = None
    discord_tag: Annotated[str | None, NumToStr] = None
    season_id: Annotated[str | None, NumToStr] = None
    access_type: str | None = None
    ttl_minutes: Annotated[str | None, NumToStr] = None
