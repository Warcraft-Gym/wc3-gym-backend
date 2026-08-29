"""Every datetime is aware UTC: a bare input is read as UTC, a zoned one
is converted, and a stored value reads back aware on every dialect."""

from datetime import UTC, datetime
from typing import Any, cast

from app.core.query import QueryUtil
from app.models.series import Series, SeriesUpdate


def test_input_lands_as_aware_utc() -> None:
    assert SeriesUpdate(date_time="2026-07-05T20:30:00+04:00").date_time == datetime(
        2026, 7, 5, 16, 30, tzinfo=UTC
    )
    assert SeriesUpdate(date_time="2026-07-05 20:30:00").date_time == datetime(
        2026, 7, 5, 20, 30, tzinfo=UTC
    )
    assert QueryUtil.read_value(
        cast(Any, Series.date_time), "date_time", "2026-07-05T20:30:00Z"
    ) == datetime(2026, 7, 5, 20, 30, tzinfo=UTC)
