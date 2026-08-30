"""Field types that reproduce the request and response shapes of the API.

Two groups. The input ones accept what the producers actually send: the
xlsx import passes raw pandas cells, the w3champions sync sends fractions
for integer columns, and the admin forms send an empty string for a
cleared field. The output ones pin what the consumers already read: the
JSON of the response models is a public contract, because the leaderboard
pages on warcraft-gym.com are generated from it offline.

Each type says which group it is in.
"""

import difflib
import enum
import numbers
from datetime import UTC, date, datetime
from functools import cache
from typing import Annotated
from zoneinfo import available_timezones

from pydantic import BeforeValidator, PlainSerializer
from sqlalchemy import DateTime, Dialect
from sqlalchemy.types import TypeDecorator

from app.models.enums import Race


def _enum_to_value[T](value: T) -> str | T:
    return value.value if isinstance(value, enum.Enum) else value


def _none_to_list[T](value: T) -> list | T:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if item is not None]
    return value


def _num_to_str[T](value: T) -> str | T:
    # These ABCs also match the numpy scalars the xlsx import passes.
    if isinstance(value, bool):
        return value
    if isinstance(value, numbers.Integral):
        return str(int(value))
    if isinstance(value, numbers.Real):
        number = float(value)
        return str(int(number)) if number.is_integer() else str(number)
    return value


def _lenient_date[T](value: T) -> date | None | T:
    # Runs before pydantic's strict date parsing.
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


def utcnow() -> datetime:
    return datetime.now(UTC)


def _aware_utc[T](value: T) -> datetime | T:
    # A bare value is UTC already; a zoned one is converted to it.
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)  # type: ignore[assignment]
        except ValueError:
            return value
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    return value


class UTCDateTime(TypeDecorator[datetime]):
    """A timestamptz column read back aware in UTC on every dialect.
    SQLite keeps no zone, so a bare value from it gets UTC again."""

    impl = DateTime(timezone=True)
    cache_ok = True

    @property
    def python_type(self) -> type[datetime]:
        return datetime

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        return None if value is None else _aware_utc(value)

    def process_result_value(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        return None if value is None else _aware_utc(value)


def _empty_str_to_none[T](value: T) -> T | None:
    return None if value == "" else value


def _suggest_race[T](value: T) -> T:
    # Clients send near misses: HUMAN for HU, ORC for OC, Random for RANDOM.
    if not isinstance(value, str):
        return value
    members = [member.value for member in Race]
    if value in members:
        return value
    closest = difflib.get_close_matches(value.upper(), members, n=1, cutoff=0.4)
    known = ", ".join(members)
    if closest:
        raise ValueError(f"'{value}' is not a race. Did you mean '{closest[0]}'?")
    raise ValueError(f"'{value}' is not a race. Valid races are {known}.")


@cache
def _time_zones() -> frozenset[str]:
    # available_timezones() walks the tzdata tree; the import validates hundreds of rows.
    return frozenset(available_timezones())


def _known_time_zone[T](value: T) -> T | None:
    if value == "" or value is None:
        return None
    if value not in _time_zones():
        raise ValueError(f"'{value}' is not an IANA time zone name")
    return value


def _round_to_int[T](value: T) -> int | T:
    # The w3champions API returns fractions for integer columns.
    if isinstance(value, float) and not value.is_integer():
        return round(value)
    return value


# Output. Pydantic writes a date as isoformat already; this pins it.
IsoDate = Annotated[
    date,
    PlainSerializer(
        lambda v: v.isoformat(), return_type=str, when_used="json-unless-none"
    ),
]

# Output. The ORM holds an enum member; the API sends the plain value.
EnumValue = BeforeValidator(_enum_to_value)
# Output. Null reads as an empty list.
NoneToList = BeforeValidator(_none_to_list)

# Input. String columns that also receive numbers: role ids, xlsx cells.
NumToStr = BeforeValidator(_num_to_str)
# Input. Date fields that arrive empty or as a full ISO datetime string.
LenientDate = BeforeValidator(_lenient_date)
# Input. Datetime fields are aware UTC; a bare value is read as UTC.
AwareUTC = BeforeValidator(_aware_utc)
# Input. Number fields where a cleared form field arrives as an empty string.
EmptyStrToNone = BeforeValidator(_empty_str_to_none)
# Input. Integer fields fed by the w3champions API, which sends fractions.
RoundToInt = BeforeValidator(_round_to_int)
# Input. Time zone fields, which take an IANA name and nothing else.
KnownTimeZone = BeforeValidator(_known_time_zone)
# Input. Race fields, where a rejected value names the member it resembles.
SuggestRace = BeforeValidator(_suggest_race)
