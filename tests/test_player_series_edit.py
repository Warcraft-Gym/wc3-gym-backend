"""The player series editor writes the fields it changes, and no more.

The editor reads the series in one transaction and writes it in another.
An admin who changes the caster between the two must keep that change, so
the write carries the date and the scores only.
"""

from typing import Any

import pytest
from fastapi import FastAPI

from app.models.series import SeriesPublic, SeriesUpdate
from app.services import player_series
from app.services.series import SeriesService
from app.services.users import UserService


def test_a_player_edit_stores_the_new_date(
    app: FastAPI, seeded: dict[str, Any]
) -> None:
    result = player_series.update_player_series(
        seeded["series_played_id"],
        {"date_time": "2026-01-09 20:00:00"},
        {},
        discord_id="1",
        discord_tag="p1",
        user_service=UserService(),
        series_service=SeriesService(user_app_service=UserService()),
    )

    assert isinstance(result, dict), result
    assert result["date_time"].startswith("2026-01-09T20:00:00")


def test_a_caster_set_after_the_read_survives_the_player_edit(
    app: FastAPI, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    series_id = seeded["series_played_id"]
    series_service = SeriesService(user_app_service=UserService())
    read_series = series_service.get

    def read_then_admin_sets_the_caster(sid: int) -> SeriesPublic:
        series = read_series(sid)
        series_service.update(sid, SeriesUpdate(caster="Grubby"))
        return series

    monkeypatch.setattr(series_service, "get", read_then_admin_sets_the_caster)

    result = player_series.update_player_series(
        series_id,
        {"date_time": "2026-01-09 20:00:00"},
        {},
        discord_id="1",
        discord_tag="p1",
        user_service=UserService(),
        series_service=series_service,
    )

    assert isinstance(result, dict), result
    written = read_series(series_id)
    assert written.caster == "Grubby"
    assert written.date_time.isoformat() == "2026-01-09T20:00:00"
