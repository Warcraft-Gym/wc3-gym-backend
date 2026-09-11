"""Blocked and free time from soft blocks, as UTC intervals. Pure: no database.

A block stores local wall-clock time and no offset, so it resolves against a
real local date in the player's zone. A local time that does not exist (spring
forward) moves forward by the length of the gap, and a local time that occurs
twice (fall back) takes the first occurrence. Both are what zoneinfo does with
fold=0, the rule RFC 5545 uses too.
"""

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models.user_block import UserBlock, UserBusy

type Interval = tuple[datetime, datetime]


def instant(day: date, at: time, zone: ZoneInfo) -> datetime:
    """The UTC instant of a local wall time on a local date."""
    return datetime.combine(day, at, tzinfo=zone).astimezone(UTC)


def blocked(
    zone_name: str | None,
    blocks: Iterable[UserBlock],
    busy: Iterable[UserBusy],
    start: datetime,
    end: datetime,
) -> list[Interval]:
    """The merged UTC intervals one player blocked inside [start, end).

    A player with no zone counts as fully free: blank means open.
    """
    if not zone_name:
        return []
    zone = ZoneInfo(zone_name)
    # A block of the local day before the window can run past midnight into it
    first = start.astimezone(zone).date() - timedelta(days=1)
    days = [
        first + timedelta(days=n)
        for n in range((end.astimezone(zone).date() - first).days + 1)
    ]
    spans = [
        (
            instant(day, block.start_local, zone),
            instant(
                day + timedelta(days=1 if block.end_local < block.start_local else 0),
                block.end_local,
                zone,
            ),
        )
        for block in blocks
        for day in days
        if block.weekdays & 1 << (day.isoweekday() - 1)
    ]
    spans += [
        (
            instant(row.first_day, time(), zone),
            instant(row.last_day + timedelta(days=1), time(), zone),
        )
        for row in busy
    ]
    return merge(spans, start, end)


def merge(spans: Iterable[Interval], start: datetime, end: datetime) -> list[Interval]:
    """Clip the spans to [start, end), drop the empty ones, join the ones that touch."""
    merged: list[Interval] = []
    for lo, hi in sorted((max(lo, start), min(hi, end)) for lo, hi in spans):
        # ponytail: a block that starts in a skipped hour and ends within the gap's length after it comes out empty, once a year
        if hi <= lo:
            continue
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def free(start: datetime, end: datetime, *blocked: list[Interval]) -> list[Interval]:
    """The parts of [start, end) that no player blocked."""
    ranges: list[Interval] = []
    cursor = start
    for lo, hi in merge([span for spans in blocked for span in spans], start, end):
        if lo > cursor:
            ranges.append((cursor, lo))
        cursor = max(cursor, hi)
    if cursor < end:
        ranges.append((cursor, end))
    return ranges
