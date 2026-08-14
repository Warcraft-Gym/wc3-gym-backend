"""Field types that reproduce the request and response shapes of the API.

Two groups. The input ones accept what the producers actually send: the
xlsx import passes raw pandas cells, the w3champions sync sends fractions
for integer columns, and the admin forms send an empty string for a
cleared field. The output ones pin what the consumers already read: the
JSON of the response models is a public contract, because the leaderboard
pages on warcraft-gym.com are generated from it offline.

Each type says which group it is in.
"""

import enum
import numbers
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer


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
    # An empty string means no value, and a datetime is truncated the way
    # the DATE column truncates it. Both run before pydantic's strict date
    # parsing.
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
    # columns.
    if isinstance(value, float) and not value.is_integer():
        return round(value)
    return value


# Output. Dates serialize as isoformat() writes them, which ends a
# timezone-aware value with '+00:00' where pydantic's default writes 'Z'.
# In python mode the objects pass through, so the database layer receives
# real date and datetime values.
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

# Output. A Race column holds an enum member when read through the ORM;
# the API has always sent the plain value.
EnumValue = BeforeValidator(_enum_to_value)
# Output. Null reads as an empty list.
NoneToList = BeforeValidator(_none_to_list)
# Output. An empty list reads as null.
EmptyToNone = BeforeValidator(_empty_to_none)
# Output. A list keeps its None items out of the response.
DropNoneItems = BeforeValidator(_drop_none_items)

# Input. String columns that also receive numbers: Discord role ids and
# the cells of the xlsx import.
NumToStr = BeforeValidator(_num_to_str)
# Input. Date fields that arrive as an empty string or as a full ISO
# datetime string from the frontend.
LenientDate = BeforeValidator(_lenient_date)
# Input. Number fields where a cleared form field arrives as an empty
# string.
EmptyStrToNone = BeforeValidator(_empty_str_to_none)
# Input. Integer fields fed by the w3champions API, which sends fractions.
RoundToInt = BeforeValidator(_round_to_int)
