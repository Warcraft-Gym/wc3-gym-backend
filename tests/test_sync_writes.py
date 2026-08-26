"""UserService reads a w3c stats row and then writes it, and a sync repeats.

Both steps are in one transaction, and the database holds each key to one
row, so a second sync updates the row it finds and adds none. When the
read misses a row another writer put there, the insert that follows hits
the constraint and the service updates that row instead of failing.
"""

from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError

from app.core.db import Session
from app.models.enums import Race
from app.models.user import User
from app.models.w3c_stats import W3CStats, W3CStatsCreate
from app.services.users import UserService
from app.services.w3c import W3CService

SEASON = 21


def stats(mmr: int, race: Race = Race.HU, season: int = SEASON) -> W3CStatsCreate:
    return W3CStatsCreate(
        wc3_season=season, race=race, mmr=mmr, wins=10, losses=5, games=15
    )


def answer_w3c(monkeypatch: pytest.MonkeyPatch, reply: list[W3CStatsCreate]) -> None:
    """The w3champions calls answer from here, so no test needs a network.

    The season comes from w3champions too when no setting names one, so the
    sync asks for both of them."""

    def get_player_stats(
        self: W3CService, bnet_name: str, season_override: int | None = None
    ) -> list[W3CStatsCreate]:
        return list(reply)

    monkeypatch.setattr(W3CService, "current_season", lambda self: SEASON)
    monkeypatch.setattr(W3CService, "get_player_stats", get_player_stats)


def stamped_at(user_id: int) -> datetime | None:
    """When the last sync of this player reached w3champions."""
    with Session() as session:
        return session.get(User, user_id).w3c_synced_at


def rows_of(user_id: int) -> list[W3CStats]:
    with Session() as session:
        return list(
            session.scalars(
                select(W3CStats)
                .where(W3CStats.user_id == user_id)
                .order_by(W3CStats.id)
            ).all()
        )


def test_a_second_sync_updates_the_row_and_adds_none(
    app: FastAPI, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = seeded["player_ids"][0]

    answer_w3c(monkeypatch, [stats(mmr=1500)])
    UserService().update_w3c_stats_by_id(user_id)
    first = rows_of(user_id)
    assert [(r.race, r.wc3_season, r.mmr) for r in first] == [(Race.HU, SEASON, 1500)]

    first_stamp = stamped_at(user_id)

    answer_w3c(monkeypatch, [stats(mmr=1600)])
    UserService().update_w3c_stats_by_id(user_id)
    second = rows_of(user_id)

    assert len(second) == len(first)
    assert second[0].id == first[0].id
    assert second[0].mmr == 1600
    # Every sync that reached w3champions moves the stamp
    assert stamped_at(user_id) > first_stamp


def test_one_sync_writes_one_row_per_race_and_season(
    app: FastAPI, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = seeded["player_ids"][0]
    answer_w3c(
        monkeypatch,
        [
            stats(mmr=1500, race=Race.HU),
            stats(mmr=1400, race=Race.OC),
            stats(mmr=1300, race=Race.HU, season=SEASON - 1),
        ],
    )
    UserService().update_w3c_stats_by_id(user_id)

    keys = {(r.race, r.wc3_season) for r in rows_of(user_id)}
    assert keys == {(Race.HU, SEASON), (Race.OC, SEASON), (Race.HU, SEASON - 1)}


def test_the_database_refuses_a_second_row_for_one_race_and_season(
    app: FastAPI, seeded: dict[str, Any]
) -> None:
    """The unique index, not the service, is what stops the duplicate."""
    user_id = seeded["player_ids"][0]
    with Session() as session, pytest.raises(IntegrityError):
        for _ in range(2):
            session.add(
                W3CStats(user_id=user_id, race=Race.HU, wc3_season=SEASON, mmr=1500)
            )
            session.flush()


def test_a_lost_race_updates_the_row_the_winner_wrote(
    app: FastAPI, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read that misses the row ends in an insert the index refuses, and
    the sync then updates the row that is there."""
    user_id = seeded["player_ids"][0]
    answer_w3c(monkeypatch, [stats(mmr=1500)])
    UserService().update_w3c_stats_by_id(user_id)
    written = rows_of(user_id)

    real_key = UserService._w3c_stats_key
    reads: list[int] = []

    def blind_first_read(
        user_id: int, w3c_stats: W3CStatsCreate
    ) -> Select[tuple[W3CStats]]:
        statement = real_key(user_id, w3c_stats)
        reads.append(1)
        # The first read stands for the one another sync wrote after
        return statement.where(W3CStats.id < 0) if len(reads) == 1 else statement

    monkeypatch.setattr(UserService, "_w3c_stats_key", staticmethod(blind_first_read))

    answer_w3c(monkeypatch, [stats(mmr=1700)])
    UserService().update_w3c_stats_by_id(user_id)

    survivors = rows_of(user_id)
    assert [r.id for r in survivors] == [r.id for r in written]
    assert survivors[0].mmr == 1700
