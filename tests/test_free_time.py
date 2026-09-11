"""Soft blocks resolved to UTC intervals, across the 2026 changeovers.

New York springs forward on 8 March and London on 29 March, so in the weeks
between the two cities sit four hours apart instead of five. London falls
back on 25 October and New York on 1 November.
"""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.core.free_time import blocked, free, instant
from app.models.user_block import UserBlock, UserBusy

LONDON, NEW_YORK = "Europe/London", "America/New_York"
WEEKDAYS, SATURDAY, SUNDAY, FRIDAY = 31, 32, 64, 16


def utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


def block(days: int, start: str, end: str) -> UserBlock:
    return UserBlock(
        user_id=1,
        weekdays=days,
        start_local=time.fromisoformat(start),
        end_local=time.fromisoformat(end),
    )


def busy(first: date, last: date) -> UserBusy:
    return UserBusy(user_id=1, first_day=first, last_day=last)


def test_new_york_work_hours_move_an_hour_earlier_in_utc_after_8_march() -> None:
    spans = blocked(
        NEW_YORK,
        [block(WEEKDAYS, "09:00", "17:00")],
        [],
        utc(2026, 3, 2),
        utc(2026, 3, 14),
    )

    assert spans == [
        *[(utc(2026, 3, d, 14), utc(2026, 3, d, 22)) for d in range(2, 7)],
        *[(utc(2026, 3, d, 13), utc(2026, 3, d, 21)) for d in range(9, 14)],
    ]


def test_london_work_hours_move_an_hour_earlier_in_utc_after_29_march() -> None:
    spans = blocked(
        LONDON,
        [block(WEEKDAYS, "09:00", "17:00")],
        [],
        utc(2026, 3, 23),
        utc(2026, 4, 4),
    )

    assert spans == [
        *[(utc(2026, 3, d, 9), utc(2026, 3, d, 17)) for d in range(23, 28)],
        (utc(2026, 3, 30, 8), utc(2026, 3, 30, 16)),
        (utc(2026, 3, 31, 8), utc(2026, 3, 31, 16)),
        *[(utc(2026, 4, d, 8), utc(2026, 4, d, 16)) for d in range(1, 4)],
    ]


@pytest.mark.parametrize(
    "day,hours_apart",
    [(date(2026, 3, 2), 5), (date(2026, 3, 9), 4), (date(2026, 3, 30), 5)],
)
def test_london_and_new_york_evenings_sit_four_hours_apart_between_the_changeovers(
    day: date, hours_apart: int
) -> None:
    evening = time(20)
    london = instant(day, evening, ZoneInfo(LONDON))
    new_york = instant(day, evening, ZoneInfo(NEW_YORK))

    assert (new_york - london).total_seconds() == hours_apart * 3600


@pytest.mark.parametrize(
    "zone,sunday,start,end,expected",
    [
        # 01:00 becomes 02:00; 01:30 does not exist and moves forward by the gap
        (LONDON, 29, "01:30", "03:00", (utc(2026, 3, 29, 1, 30), utc(2026, 3, 29, 2))),
        # 02:00 becomes 03:00; 02:30 does not exist and moves forward by the gap
        (NEW_YORK, 8, "02:30", "04:00", (utc(2026, 3, 8, 7, 30), utc(2026, 3, 8, 8))),
    ],
)
def test_a_skipped_local_time_moves_forward(
    zone: str, sunday: int, start: str, end: str, expected: tuple[datetime, datetime]
) -> None:
    day = utc(2026, 3, sunday)
    spans = blocked(
        zone, [block(SUNDAY, start, end)], [], day, utc(2026, 3, sunday + 1)
    )

    assert spans == [expected]


@pytest.mark.parametrize(
    "zone,day,expected",
    [
        # 01:30 happens in BST and again in GMT; the block starts at the first
        (LONDON, date(2026, 10, 25), (utc(2026, 10, 25, 0, 30), utc(2026, 10, 25, 3))),
        # 01:30 happens in EDT and again in EST; the block starts at the first
        (NEW_YORK, date(2026, 11, 1), (utc(2026, 11, 1, 5, 30), utc(2026, 11, 1, 8))),
    ],
)
def test_a_doubled_local_time_takes_the_first(
    zone: str, day: date, expected: tuple[datetime, datetime]
) -> None:
    start = datetime.combine(day, time(), tzinfo=UTC)
    spans = blocked(
        zone,
        [block(SUNDAY, "01:30", "03:00")],
        [],
        start,
        utc(2026, day.month, day.day, 23),
    )

    assert spans == [expected]


def test_a_block_past_midnight_ends_on_the_next_day() -> None:
    """Friday 22:00 to 02:00 in London winter holds the small hours of Saturday."""
    late = block(FRIDAY, "22:00", "02:00")

    assert blocked(LONDON, [late], [], utc(2026, 1, 9), utc(2026, 1, 11)) == [
        (utc(2026, 1, 9, 22), utc(2026, 1, 10, 2))
    ]
    # A window that opens on Saturday still holds the tail of Friday's block
    assert blocked(LONDON, [late], [], utc(2026, 1, 10), utc(2026, 1, 11)) == [
        (utc(2026, 1, 10), utc(2026, 1, 10, 2))
    ]


def test_a_block_past_midnight_into_the_spring_forward_is_an_hour_shorter() -> None:
    """Saturday 23:00 to 02:00 over the London changeover lasts two real hours."""
    spans = blocked(
        LONDON,
        [block(SATURDAY, "23:00", "02:00")],
        [],
        utc(2026, 3, 28),
        utc(2026, 3, 30),
    )

    assert spans == [(utc(2026, 3, 28, 23), utc(2026, 3, 29, 1))]


def test_a_busy_day_is_the_whole_local_day_even_a_short_one() -> None:
    spans = blocked(
        LONDON,
        [],
        [busy(date(2026, 3, 29), date(2026, 3, 29))],
        utc(2026, 3, 28),
        utc(2026, 3, 31),
    )

    assert spans == [(utc(2026, 3, 29), utc(2026, 3, 29, 23))]


def test_blank_means_open() -> None:
    """No zone or no blocks: the player is free the whole window."""
    start, end = utc(2026, 1, 5), utc(2026, 1, 12)

    assert blocked(None, [block(127, "00:00", "23:00")], [], start, end) == []
    assert blocked(LONDON, [], [], start, end) == []
    assert free(start, end, [], []) == [(start, end)]


def test_free_time_is_what_neither_player_blocked() -> None:
    start, end = utc(2026, 1, 5), utc(2026, 1, 6)
    london = blocked(LONDON, [block(127, "00:00", "08:00")], [], start, end)
    new_york = blocked(NEW_YORK, [block(127, "09:00", "17:00")], [], start, end)

    assert free(start, end, london, new_york) == [
        (utc(2026, 1, 5, 8), utc(2026, 1, 5, 14)),
        (utc(2026, 1, 5, 22), end),
    ]
