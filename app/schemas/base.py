"""Shared Pydantic base class for the schemas that still live here.

The field types moved to app/models/types.py, next to the model families
that use them. The names below re-export them for the schemas that have
not been converted yet.

The JSON produced by to_dict() is a public contract consumed by the
warcraft-gym.com pages - field names and value shapes must not change.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.types import (
    DropNoneItems,
    EmptyStrToNone,
    EmptyToNone,
    EnumValue,
    IsoDate,
    IsoDateTime,
    LenientDate,
    NoneToList,
    NumToStr,
    RoundToInt,
)

__all__ = [
    "APISchema",
    "DropNoneItems",
    "EmptyStrToNone",
    "EmptyToNone",
    "EnumValue",
    "IsoDate",
    "IsoDateTime",
    "LenientDate",
    "NoneToList",
    "NumToStr",
    "RoundToInt",
]

_UNSET: Any = object()


class APISchema(BaseModel):
    # validate_assignment: the service layer mutates these objects in place
    # (e.g. `team.player_by_season = {...}`), and those values must go
    # through the same validators as constructor input.
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    def __init__(self, data: dict | None = _UNSET, **kwargs):
        # The old DTOs were constructed as `SomeDTO(request.json)`; keep that
        # calling convention alongside regular keyword construction. A None
        # payload raised in the old DTOs (`None.get(...)`) and must not
        # silently build an all-default object here.
        if data is _UNSET:
            super().__init__(**kwargs)
        else:
            super().__init__(**data)

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")
