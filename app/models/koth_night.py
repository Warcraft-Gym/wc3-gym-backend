"""What an admin names to open a KOTH night; the night itself is an event row."""

from datetime import datetime
from typing import Annotated

from sqlmodel import SQLModel

from app.models.types import AwareUTC, NumToStr


class NightOpen(SQLModel):
    """Tonight's night: when it starts, what it is called, where it cuts.

    The bounds are the MMR each bracket opens at, weakest first, so the list
    reads the way the bracket numbers do. Left out, the night takes the bounds
    of the night before.
    """

    starts_at: Annotated[datetime, AwareUTC]
    name: Annotated[str | None, NumToStr] = None
    lower_bounds: list[int] | None = None
