"""UserService reads a row and then writes it, and a sync repeats.

Both steps are in one transaction, and the database holds each key to one
row, so a second sync updates the row it finds and adds none. When the
read misses a row another writer put there, the insert that follows hits
the constraint and the service updates that row instead of failing.
"""

from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from app.core.db import Session
from app.models.enums import Race
from app.models.user_team_season import DBUserTeamSeason, UserTeamSeasonStatsPublic
from app.models.w3c_stats import W3CStats, W3CStatsCreate
from app.services.users import UserService
from app.services.w3c import W3CService

SEASON = 21


def stats(mmr: int, race: Race = Race.HU, season: int = SEASON) -> W3CStatsCreate:
    return W3CStatsCreate(
        wc3_season=season, race=race, mmr=mmr, wins=10, losses=5, games=15
    )


def answer_w3c(monkeypatch: pytest.MonkeyPatch, reply: list[W3CStatsCreate]) -> None:
    """The w3champions call answers this list, so no test needs a network."""

    def getPlayerStats(
        self: W3CService, bnet_name: str, season_override: int | None = None
    ) -> list[W3CStatsCreate]:
        return list(reply)

    monkeypatch.setattr(W3CService, "getPlayerStats", getPlayerStats)


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
    UserService().updateW3CStats_ById(user_id)
    first = rows_of(user_id)
    assert [(r.race, r.wc3_season, r.mmr) for r in first] == [(Race.HU, SEASON, 1500)]

    answer_w3c(monkeypatch, [stats(mmr=1600)])
    UserService().updateW3CStats_ById(user_id)
    second = rows_of(user_id)

    assert len(second) == len(first)
    assert second[0].id == first[0].id
    assert second[0].mmr == 1600


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
    UserService().updateW3CStats_ById(user_id)

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
    UserService().updateW3CStats_ById(user_id)
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
    UserService().updateW3CStats_ById(user_id)

    survivors = rows_of(user_id)
    assert [r.id for r in survivors] == [r.id for r in written]
    assert survivors[0].mmr == 1700


def test_a_lost_season_stats_race_updates_the_row_the_winner_wrote(
    app: FastAPI, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The composite primary key refuses the second insert, and the write
    falls through to the update rather than failing the request."""
    real_get = OrmSession.get
    missed: list[int] = []

    def blind_first_get(
        self: OrmSession, entity: type[object], ident: object, **kwargs: object
    ) -> object | None:
        # The first read stands for the one another writer filled in after
        if entity is DBUserTeamSeason and not missed:
            missed.append(1)
            return None
        return real_get(self, entity, ident, **kwargs)

    monkeypatch.setattr(OrmSession, "get", blind_first_get)

    user = UserService().updateUserTeamSeasonStats(
        UserTeamSeasonStatsPublic(
            user_id=seeded["player_ids"][0],
            team_id=seeded["team_a_id"],
            season_id=seeded["season_id"],
            games=7,
            wins=5,
            losses=2,
            matchup_history=[Race.NE.value],
        )
    )

    assert missed == [1]
    with Session() as session:
        rows = session.scalars(select(DBUserTeamSeason)).all()
    assert len([r for r in rows if r.user_id == user.id]) == 1
    assert [(r.games, r.wins, r.losses) for r in rows if r.user_id == user.id] == [
        (7, 5, 2)
    ]
