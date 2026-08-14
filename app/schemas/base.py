"""Shared Pydantic base class and validation helpers for the API schemas.

They keep the class names, constructor style and to_dict()/to_db_dict()
surface that the api/service/database layers use, while giving us real
Pydantic models for a future FastAPI port.

The JSON produced by to_dict() is a public contract consumed by the
warcraft-gym.com frontend pages - field names and value shapes must not
change.
"""

import enum
import numbers
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, PlainSerializer


def _enum_to_value(value: Any) -> Any:
    return value.value if isinstance(value, enum.Enum) else value


def _none_to_list(value: Any) -> Any:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if item is not None]
    return value


def _num_to_str(value: Any) -> Any:
    # numbers.Integral and numbers.Real also match numpy scalars, which the
    # xlsx import passes for numeric cells (pandas reads a column as int64,
    # or as float64 when the column has blank cells).
    if isinstance(value, bool):
        return value
    if isinstance(value, numbers.Integral):
        return str(int(value))
    if isinstance(value, numbers.Real):
        value = float(value)
        return str(int(value)) if value.is_integer() else str(value)
    return value


def _empty_to_none(value: Any) -> Any:
    if isinstance(value, list):
        value = [item for item in value if item is not None]
    return value if value else None


def _drop_none_items(value: Any) -> Any:
    if isinstance(value, list):
        return [item for item in value if item is not None]
    return value


def _lenient_date(value: Any) -> Any:
    # The old DTOs stored raw request values for date fields: an empty string
    # became no value, and MySQL truncated a datetime to the DATE column.
    # Reproduce both before pydantic's strict date parsing runs.
    if value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return value
        return parsed.date()
    return value


def _empty_str_to_none(value: Any) -> Any:
    return None if value == "" else value


def _round_to_int(value: Any) -> Any:
    # The w3champions API sometimes returns fractional numbers for integer
    # columns; MySQL rounded them on insert for the old DTOs.
    if isinstance(value, float) and not value.is_integer():
        return round(value)
    return value


# Date/datetime fields must serialize to JSON exactly like the old DTOs'
# `.isoformat()` calls (pydantic's default differs for timezone-aware values:
# 'Z' instead of '+00:00'). In python mode (to_db_dict) the objects pass
# through untouched, so the DB layer receives real date/datetime values.
IsoDateTime = Annotated[
    datetime,
    PlainSerializer(
        lambda v: v.isoformat(), return_type=str, when_used="json-unless-none"
    ),
]
IsoDate = Annotated[
    date,
    PlainSerializer(
        lambda v: v.isoformat(), return_type=str, when_used="json-unless-none"
    ),
]

# Race columns hold Race enum members when read via SQLAlchemy; the API always
# exposed the plain value (via the app's custom JSON provider), so normalize
# to the value at validation time.
EnumValue = BeforeValidator(_enum_to_value)
# Fields the old DTOs serialized as 'x if x else []'.
NoneToList = BeforeValidator(_none_to_list)
# Fields the old DTOs serialized as 'x if x else None' (empty list -> null).
EmptyToNone = BeforeValidator(_empty_to_none)
# List fields where the old to_dict() skipped None items but the attribute
# itself kept the list (or None) it was given.
DropNoneItems = BeforeValidator(_drop_none_items)
# String fields that sometimes receive numbers (Discord role IDs and other
# cells from the xlsx import). The old DTOs passed them through and MySQL
# stored the digits; convert to the same string up front.
NumToStr = BeforeValidator(_num_to_str)
# Date fields that the old DTOs accepted as empty strings or full ISO
# datetime strings from the frontend.
LenientDate = BeforeValidator(_lenient_date)
# Number fields where the frontend sends an empty string for a cleared
# input; the old DTOs kept the value and later code treated it as unset.
EmptyStrToNone = BeforeValidator(_empty_str_to_none)
# Integer fields fed by the w3champions API, which can send fractions.
RoundToInt = BeforeValidator(_round_to_int)


_UNSET: Any = object()


class APISchema(BaseModel):
    # validate_assignment: the service layer mutates these objects in place
    # (e.g. `map.id = None`, `team.player_by_season = {...}`), and those
    # values must go through the same validators as constructor input.
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
