"""The ladder sync: parse w3champions matches, page them, store them once.

The parser runs against pages captured from w3champions (tests/data/w3c,
written by capture.py), so the shape under test is the shape the service
answers with.
"""

import inspect
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import Client
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from app.api.routes.seasons import sync_ladder_season_signups
from app.core.db import Session
from app.core.exceptions import W3CThrottledError
from app.models.enums import Race
from app.models.ladder_sync import LadderSync
from app.models.relationships import DBUserSeasonSignup
from app.models.season import Season
from app.models.user import User, UserCreate, UserReduced
from app.models.user_team_season import DBUserTeamSeason
from app.models.w3c_ladder_match import W3CLadderMatch, W3CLadderMatchCreate
from app.models.w3c_stats import W3CStats, W3CStatsCreate
from app.services import w3c as w3c_module
from app.services.ladder import LadderService
from app.services.users import W3C_SYNC_WORKERS, UserService
from app.services.w3c import THROTTLED_MESSAGE, W3CService

FIXTURES = Path(__file__).parent / "data" / "w3c"

# The w3champions season the fixtures were captured from.
W3C_SEASON = 25

# Before every match in the fixtures.
SINCE = datetime(2026, 1, 1)


def fixture(name: str) -> list[dict[str, Any]]:
    """One captured page, newest match first."""
    matches = json.loads((FIXTURES / f"{name}.json").read_text())["matches"]
    return sorted(matches, key=lambda match: match["startTime"], reverse=True)


THANKS = fixture("thanks_11187_season25")
PSIKE = fixture("psike_1331_season25")


class FakeW3C:
    """W3Champions with a fixed set of matches per season, and a call log."""

    def __init__(
        self,
        by_season: dict[int, list[dict[str, Any]]],
        throttle_on: int | None = None,
    ) -> None:
        self.by_season = by_season
        self.throttle_on = throttle_on
        self.calls: list[tuple[int, int]] = []
        # The `since` each season was last paged from, which is what makes a
        # read of the open season incremental
        self.since: dict[int, datetime] = {}

    def send_request(
        self, method: str, url: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        season, offset = params["season"], params["offset"]
        self.calls.append((season, offset))
        if season == self.throttle_on:
            raise W3CThrottledError(THROTTLED_MESSAGE)
        matches = self.by_season.get(season, [])
        return {
            "matches": matches[offset : offset + params["pageSize"]],
            "count": len(matches),
        }

    def seasons(self) -> list[int]:
        return [season for season, _ in self.calls]


def serve(
    monkeypatch: pytest.MonkeyPatch,
    by_season: dict[int, list[dict[str, Any]]],
    page_size: int = 100,
    throttle_on: int | None = None,
) -> FakeW3C:
    fake = FakeW3C(by_season, throttle_on)
    paged = W3CService._page_season

    def page(
        self: W3CService,
        battle_tag: str,
        season: int,
        since: datetime,
        rows: dict[str, Any],
    ) -> tuple[bool, bool]:
        fake.since[season] = since
        return paged(self, battle_tag, season, since, rows)

    monkeypatch.setattr(w3c_module, "MATCH_PAGE_SIZE", page_size)
    monkeypatch.setattr(W3CService, "send_request", fake.send_request)
    # One sync reads the stats too; these tests are about the matches
    monkeypatch.setattr(
        W3CService, "get_player_stats", lambda self, tag, season_override=None: []
    )
    monkeypatch.setattr(W3CService, "current_season", lambda self: W3C_SEASON)
    monkeypatch.setattr(W3CService, "_page_season", page)
    return fake


def at(match_id: str, season: int, when: datetime) -> dict[str, Any]:
    """One captured match, moved to this w3champions season and start time."""
    return {
        **THANKS[0],
        "id": match_id,
        "season": season,
        "startTime": when.replace(tzinfo=UTC).isoformat(),
    }


def add_player(name: str, battle_tag: str) -> UserReduced:
    return UserService().add(
        UserCreate(
            name=name,
            battleTag=battle_tag,
            discordTag=name,
            discordId=str(abs(hash(name)) % 10000),
            race=Race.HU,
        )
    )


def sign_up(season_id: int, user_id: int, team_id: int | None = None) -> None:
    """Sign a player up, and put him on a team when one is named."""
    with Session() as session:
        session.add(DBUserSeasonSignup(user_id=user_id, season_id=season_id))
        if team_id is not None:
            session.add(
                DBUserTeamSeason(user_id=user_id, team_id=team_id, season_id=season_id)
            )
        session.commit()


def store_match(user_id: int, season: int, start_time: datetime) -> None:
    """One stored match, which is what dates a w3champions season."""
    with Session() as session:
        session.add(
            W3CLadderMatch(
                w3c_match_id=f"stored-{season}",
                user_id=user_id,
                wc3_season=season,
                start_time=start_time,
                duration_s=600,
                won=True,
            )
        )
        session.commit()


def ledger_of(user_id: int) -> dict[int, LadderSync]:
    """What the sync has recorded for this player, by w3champions season."""
    with Session() as session:
        return {
            row.wc3_season: row
            for row in session.scalars(
                select(LadderSync).where(LadderSync.user_id == user_id)
            )
        }


def mark(user_id: int, season: int, complete: bool) -> None:
    """A ledger row as an earlier run left it."""
    with Session() as session:
        session.add(
            LadderSync(
                user_id=user_id,
                wc3_season=season,
                synced_at=datetime(2026, 3, 1),
                complete=complete,
            )
        )
        session.commit()


def stored() -> list[W3CLadderMatch]:
    with Session() as session:
        return list(session.scalars(select(W3CLadderMatch)))


def started_before(matches: list[dict[str, Any]], since: datetime) -> int:
    """The position of the first match older than `since`."""
    for index, match in enumerate(matches):
        if datetime.fromisoformat(match["startTime"]).replace(tzinfo=None) < since:
            return index
    raise AssertionError("every match in the page is newer than since")


# The parser, over the captured pages.


def test_the_parser_reads_a_captured_page() -> None:
    """Two rows per match, one per player, with the fields the table holds."""
    rows = [row for match in THANKS for row in W3CService().parse_match(match)]

    assert len(rows) == 2 * len(THANKS)
    row = next(r for r in rows if r.w3c_match_id == "6a6ea769ea6bb176a031b63d")
    assert row.battleTag == "rhaxtamanN#2250"
    opponent = next(
        r
        for r in rows
        if r.w3c_match_id == row.w3c_match_id and r.battleTag == "thanks#11187"
    )
    assert opponent.start_time == datetime(2026, 8, 2, 1, 55, 12, 626000)
    assert opponent.wc3_season == W3C_SEASON
    assert opponent.duration_s == 1000
    assert opponent.map_name == "Last Refuge"
    assert opponent.race == Race.NE
    assert opponent.won is False
    assert opponent.opp_battletag == "rhaxtamanN#2250"
    assert opponent.opp_race == Race.UD
    assert (opponent.mmr_before, opponent.mmr_after) == (1379, 1369)
    assert row.won is True


def test_a_random_pick_keeps_the_pick_and_the_roll() -> None:
    """The league scores the selected race, so a random pick stays RANDOM."""
    match, player = next(
        (match, player)
        for match in THANKS + PSIKE
        for team in match["teams"]
        for player in team["players"]
        if player["race"] == 0 and player["rndRace"] is not None
    )

    row = next(
        r for r in W3CService().parse_match(match) if r.battleTag == player["battleTag"]
    )

    assert row.race is Race.RANDOM
    assert row.played_race == W3CService().get_race_enum(player["rndRace"])
    assert row.played_race is not Race.RANDOM


def test_a_normal_pick_reads_the_same_race_twice() -> None:
    """Nothing was rolled, so the selected race is the race played."""
    match, player = next(
        (match, player)
        for match in THANKS + PSIKE
        for team in match["teams"]
        for player in team["players"]
        if player["race"] != 0
    )

    row = next(
        r for r in W3CService().parse_match(match) if r.battleTag == player["battleTag"]
    )

    assert row.race == W3CService().get_race_enum(player["race"])
    assert row.played_race == row.race


# The walk over pages and seasons.


def test_the_paging_stops_at_the_first_page_older_than_since(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    since = datetime(2026, 7, 30)
    fake = serve(monkeypatch, {W3C_SEASON: THANKS}, page_size=10)

    W3CService().get_player_matches("thanks#11187", [(W3C_SEASON, since)])

    last = started_before(THANKS, since)
    assert fake.calls == [(W3C_SEASON, offset) for offset in range(0, last + 1, 10)]


def test_the_walk_reads_past_the_seasons_the_player_sat_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Silent seasons say nothing about the ones below them."""
    fake = serve(
        monkeypatch,
        {W3C_SEASON - 2: THANKS[:20], W3C_SEASON - 3: PSIKE[:5]},
        page_size=10,
    )

    rows, complete = W3CService().walk_player_matches("thanks#11187", W3C_SEASON, SINCE)

    assert fake.seasons() == [25, 24, 23, 23, 23, 22, 21, 20, 19]
    assert set(complete) == {25, 24, 23, 22, 21, 20, 19}
    assert len({row.w3c_match_id for row in rows}) == 25


def test_the_walk_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every season answers, so only the cap ends the walk."""
    every_season = dict.fromkeys(range(W3C_SEASON + 1), THANKS[:5])
    fake = serve(monkeypatch, every_season, page_size=10)

    W3CService().walk_player_matches("thanks#11187", W3C_SEASON, SINCE)

    assert fake.seasons() == [25, 24, 23, 22, 21, 20, 19]


# The sync, against the database.


def test_a_sync_writes_no_row_for_the_opponent(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The payload carries both sides; a worker writes the player it syncs."""
    match = next(m for m in THANKS if m["id"] == "6a6ea769ea6bb176a031b63d")
    thanks = add_player("thanks", "thanks#11187")
    rhax = add_player("rhax", "rhaxtamanN#2250")
    serve(monkeypatch, {W3C_SEASON: [match]})

    result = LadderService().sync_users([thanks], SINCE)

    assert result.synced == [thanks.id]
    rows = {row.user_id: row for row in stored()}
    assert set(rows) == {thanks.id}
    assert rows[thanks.id].won is False
    assert rows[thanks.id].opp_battletag == "rhaxtamanN#2250"
    assert rhax.id not in rows


def test_a_second_sync_writes_no_second_row(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    thanks = add_player("thanks", "thanks#11187")
    serve(monkeypatch, {W3C_SEASON: THANKS[:5]})

    LadderService().sync_users([thanks], SINCE)
    first = len(stored())
    LadderService().sync_users([thanks], SINCE)

    assert first == 5
    assert len(stored()) == first


def test_a_player_w3champions_refuses_does_not_stop_the_others(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    thanks = add_player("thanks", "thanks#11187")
    psike = add_player("psike", "Psike#1331")
    serve(monkeypatch, {W3C_SEASON: THANKS[:3]})
    real = W3CService.get_player_matches

    def refuse_one(
        self: W3CService, battle_tag: str, seasons: list[tuple[int, datetime]]
    ) -> tuple[list[Any], dict[int, bool]]:
        if battle_tag == "Psike#1331":
            raise Exception("Request failed with status code 404: player not found")
        return real(self, battle_tag, seasons)

    monkeypatch.setattr(W3CService, "get_player_matches", refuse_one)

    result = LadderService().sync_users([thanks, psike], SINCE, [W3C_SEASON])

    assert result.synced == [thanks.id]
    assert [(f.id, f.battleTag) for f in result.failed] == [(psike.id, "Psike#1331")]
    assert "404" in result.failed[0].reason
    assert len(stored()) == 3


def test_a_player_with_no_matches_is_stamped(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stamp says when the app last asked, not that matches were found."""
    thanks = add_player("thanks", "thanks#11187")
    serve(monkeypatch, {})

    LadderService().sync_users([thanks], SINCE)

    with Session() as session:
        assert session.get(User, thanks.id).ladder_synced_at is not None
    assert stored() == []


def test_the_season_sync_reads_the_seasons_its_window_sits_in(
    app: FastAPI, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stored matches of the window name the seasons, so nothing else is read."""
    player = seeded["player_ids"][0]
    sign_up(seeded["season_id"], player)
    # The seeded season runs 2026-01-05 to 2026-02-27
    store_match(player, W3C_SEASON - 5, datetime(2026, 1, 10))
    store_match(player, W3C_SEASON, datetime(2026, 8, 1))
    fake = serve(monkeypatch, {})

    LadderService().sync_season(seeded["season_id"])

    assert fake.seasons() == [20]
    assert ledger_of(player)[20].complete is True


def test_a_season_still_running_starts_the_walk_at_the_pinned_season(
    app: FastAPI, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """No stored match names a season w3champions only just opened."""
    player = seeded["player_ids"][0]
    sign_up(seeded["season_id"], player)
    store_match(player, W3C_SEASON - 1, datetime(2026, 1, 10))
    with Session() as session:
        session.get(Season, seeded["season_id"]).end_date = None
        session.commit()
    fake = serve(monkeypatch, {})

    LadderService().sync_season(seeded["season_id"])

    assert fake.seasons()[0] == W3C_SEASON


def test_the_season_sync_starts_at_the_pin_while_nothing_is_stored(
    app: FastAPI, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first sync of all has no match to date a season by."""
    sign_up(seeded["season_id"], seeded["player_ids"][0])
    fake = serve(monkeypatch, {})

    LadderService().sync_season(seeded["season_id"])

    assert fake.seasons()[0] == W3C_SEASON


def test_a_closed_season_read_to_its_end_is_never_read_again(
    app: FastAPI, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resync of an old season costs no w3champions call."""
    player = seeded["player_ids"][0]
    sign_up(seeded["season_id"], player)
    store_match(player, W3C_SEASON - 1, datetime(2026, 1, 10))
    fake = serve(monkeypatch, {})

    LadderService().sync_season(seeded["season_id"])
    assert fake.seasons() == [W3C_SEASON - 1]
    assert ledger_of(player)[W3C_SEASON - 1].complete is True
    fake.calls.clear()
    LadderService().sync_season(seeded["season_id"])

    assert fake.calls == []


def test_a_season_read_only_in_part_is_read_again_in_full(
    app: FastAPI, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unfinished walk left no matches to trust, so the window is read again."""
    player = seeded["player_ids"][0]
    sign_up(seeded["season_id"], player)
    store_match(player, W3C_SEASON - 1, datetime(2026, 1, 10))
    mark(player, W3C_SEASON - 1, complete=False)
    fake = serve(monkeypatch, {})

    LadderService().sync_season(seeded["season_id"])

    assert fake.seasons() == [W3C_SEASON - 1]
    # The whole window, not the stamp the unfinished run left
    assert fake.since[W3C_SEASON - 1] == datetime(2026, 1, 5)


def test_a_walk_that_stops_early_is_written_as_unfinished(
    app: FastAPI, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ledger records what the pager reached, so a short read is no skip."""
    player = seeded["player_ids"][0]
    sign_up(seeded["season_id"], player)
    store_match(player, W3C_SEASON - 1, datetime(2026, 1, 10))
    serve(monkeypatch, {})
    monkeypatch.setattr(W3CService, "_page_season", lambda *args: (False, False))

    LadderService().sync_season(seeded["season_id"])

    assert ledger_of(player)[W3C_SEASON - 1].complete is False


def test_a_throttle_keeps_the_seasons_read_before_it(
    app: FastAPI, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The finished season is written and stamped; the refused one is not."""
    thanks = add_player("thanks", "thanks#11187")
    sign_up(seeded["season_id"], thanks.id, seeded["team_a_id"])
    # The window sits in two w3champions seasons, read newest first
    store_match(thanks.id, W3C_SEASON, datetime(2026, 1, 10))
    store_match(thanks.id, W3C_SEASON - 1, datetime(2026, 1, 11))
    serve(monkeypatch, {W3C_SEASON: THANKS[:3]}, throttle_on=W3C_SEASON - 1)

    result = LadderService().sync_season(seeded["season_id"])

    assert [failure.reason for failure in result.failed] == [THROTTLED_MESSAGE]
    assert len(stored()) == 5
    ledger = ledger_of(thanks.id)
    assert ledger[W3C_SEASON].complete is True
    assert W3C_SEASON - 1 not in ledger


def test_the_open_season_is_read_again_from_its_own_stamp(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second read asks for the matches since the first one, and no more."""
    thanks = add_player("thanks", "thanks#11187")
    fake = serve(monkeypatch, {W3C_SEASON: THANKS[:3]})

    LadderService().sync_users([thanks], SINCE, [W3C_SEASON])
    assert fake.since[W3C_SEASON] == SINCE
    stamp = ledger_of(thanks.id)[W3C_SEASON].synced_at
    LadderService().sync_users([thanks], SINCE, [W3C_SEASON])

    assert fake.since[W3C_SEASON] == stamp


def test_the_first_sync_of_a_window_walks_and_writes_what_it_found(
    app: FastAPI, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """No stored match names a season, so the walk discovers them."""
    player = seeded["player_ids"][0]
    sign_up(seeded["season_id"], player)
    fake = serve(monkeypatch, {W3C_SEASON - 2: THANKS[:3]})

    LadderService().sync_season(seeded["season_id"])

    assert fake.seasons()[0] == W3C_SEASON
    assert set(ledger_of(player)) == set(fake.seasons())


# The window this bootstrap walk reads: it starts inside season 23.
WINDOW = datetime(2026, 1, 18)


def test_the_bootstrap_walk_records_every_season_it_read(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A window two seasons below the pin stamps every season down to it."""
    thanks = add_player("thanks", "thanks#11187")
    fake = serve(
        monkeypatch,
        {
            25: [at("s25", 25, datetime(2026, 7, 1))],
            24: [at("s24", 24, datetime(2026, 2, 10))],
            23: [
                at("s23-in", 23, datetime(2026, 1, 20)),
                at("s23-out", 23, datetime(2026, 1, 10)),
            ],
        },
    )

    LadderService().sync_users([thanks], WINDOW)

    assert fake.seasons() == [25, 24, 23]
    ledger = ledger_of(thanks.id)
    assert sorted(ledger) == [23, 24, 25]
    assert all(row.complete for row in ledger.values())
    # Season 23 holds the start of the window, so the walk never reaches 22
    assert 22 not in ledger
    stored_ids = {row.w3c_match_id for row in stored()}
    assert {"s24", "s23-in"} <= stored_ids


def test_the_bootstrap_walk_records_an_empty_season_it_passed_through(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A season the player sat out was read, so it is complete."""
    thanks = add_player("thanks", "thanks#11187")
    serve(
        monkeypatch,
        {
            25: [at("s25", 25, datetime(2026, 7, 1))],
            23: [
                at("s23-in", 23, datetime(2026, 1, 20)),
                at("s23-out", 23, datetime(2026, 1, 10)),
            ],
        },
    )

    LadderService().sync_users([thanks], WINDOW)

    ledger = ledger_of(thanks.id)
    assert ledger[24].complete is True
    assert "s23-in" in {row.w3c_match_id for row in stored()}


def test_a_database_error_names_its_class(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The admin reads which database error it was, and no statement."""
    thanks = add_player("thanks", "thanks#11187")
    serve(monkeypatch, {W3C_SEASON: THANKS[:1]})

    def clash(
        self: LadderService,
        session: OrmSession,
        user_id: int,
        rows: list[W3CLadderMatchCreate],
    ) -> None:
        raise IntegrityError("statement", {}, Exception("duplicate key"))

    monkeypatch.setattr(LadderService, "_write_matches", clash)

    result = LadderService().sync_users([thanks], SINCE, [W3C_SEASON])

    assert [f.reason for f in result.failed] == ["Database error (IntegrityError)"]


# The route. It runs in chunks, because one request per season would outlive
# a serverless function.


def test_the_ladder_sync_route_needs_a_token(client: Client) -> None:
    assert client.post("/seasons/1/ladder-sync").status_code == 401


def test_the_ladder_sync_route_pages_through_the_signups(
    client: Client,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signed_up = seeded["player_ids"][:3]
    resp = client.post(
        f"/seasons/{seeded['season_id']}/signups",
        json={"user_ids": signed_up},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    serve(monkeypatch, {})
    url = f"/seasons/{seeded['season_id']}/ladder-sync"

    first = client.post(f"{url}?limit=2", headers=auth_headers)
    second = client.post(f"{url}?limit=2&offset=2", headers=auth_headers)

    assert first.status_code == 200
    assert first.json() == {
        "synced": signed_up[:2],
        "skipped": [],
        "failed": [],
        "total": 3,
        "next_offset": 2,
    }
    assert second.json()["synced"] == signed_up[2:]
    assert second.json()["next_offset"] is None


def test_the_ladder_sync_route_stores_the_matches_of_the_signups(
    client: Client,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The window starts at the season start date, so the chunk backfills."""
    player = seeded["player_ids"][0]
    with Session() as session:
        session.get(User, player).battleTag = "thanks#11187"
        session.commit()
    client.post(
        f"/seasons/{seeded['season_id']}/signups",
        json={"user_ids": [player]},
        headers=auth_headers,
    )
    serve(monkeypatch, {W3C_SEASON: THANKS[:4]})

    resp = client.post(
        f"/seasons/{seeded['season_id']}/ladder-sync", headers=auth_headers
    )

    assert resp.status_code == 200
    assert resp.json()["synced"] == [player]
    with Session() as session:
        assert session.scalar(select(func.count()).select_from(W3CLadderMatch)) == 4


def test_the_season_sync_counts_the_players_on_a_team(
    app: FastAPI, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ladder page shows the players on a team, so the sync walks those."""
    for player in seeded["player_ids"]:
        sign_up(seeded["season_id"], player)
    bench = add_player("bench", "bench#9999")
    sign_up(seeded["season_id"], bench.id)
    serve(monkeypatch, {})

    result = LadderService().sync_season(seeded["season_id"])

    assert result.total == len(seeded["player_ids"])
    assert result.synced == seeded["player_ids"]
    assert bench.id not in result.synced


def test_a_player_synced_a_moment_ago_is_skipped(
    app: FastAPI, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second press of the button costs no w3champions call."""
    for player in seeded["player_ids"]:
        sign_up(seeded["season_id"], player)
    fake = serve(monkeypatch, {})

    first = LadderService().sync_season(seeded["season_id"])
    fake.calls.clear()
    second = LadderService().sync_season(seeded["season_id"])

    assert first.synced == seeded["player_ids"]
    assert second.skipped == seeded["player_ids"]
    assert second.synced == []
    assert fake.calls == []


def test_a_player_is_synced_again_once_max_age_has_passed(
    app: FastAPI, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    for player in seeded["player_ids"]:
        sign_up(seeded["season_id"], player)
    serve(monkeypatch, {})

    LadderService().sync_season(seeded["season_id"])
    result = LadderService().sync_season(
        seeded["season_id"], max_age=timedelta(seconds=0)
    )

    assert result.skipped == []
    assert result.synced == seeded["player_ids"]


def test_the_ladder_sync_route_syncs_one_worker_wave() -> None:
    """One chunk is one wave of workers, so the default limit is that many."""
    limit = inspect.signature(sync_ladder_season_signups).parameters["limit"]

    assert limit.default == W3C_SYNC_WORKERS


def test_one_sync_writes_the_stats_and_the_matches_of_a_player(
    app: FastAPI, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """One press per player: his MMR row and his ladder rows in one worker."""
    player = seeded["player_ids"][0]
    with Session() as session:
        session.get(User, player).battleTag = "thanks#11187"
        session.commit()
    sign_up(seeded["season_id"], player)
    serve(monkeypatch, {W3C_SEASON: THANKS[:2]})
    monkeypatch.setattr(
        W3CService,
        "get_player_stats",
        lambda self, tag, season_override=None: [
            W3CStatsCreate(wc3_season=season_override, race=Race.HU, mmr=1500, games=20)
        ],
    )

    result = LadderService().sync_season(seeded["season_id"])

    assert result.synced == [player]
    with Session() as session:
        stats = session.scalars(
            select(W3CStats).where(W3CStats.user_id == player)
        ).all()
        user = session.get(User, player)
    assert [row.mmr for row in stats] == [1500, 1500]
    assert len(stored()) == 2
    assert user.w3c_synced_at is not None
    assert user.ladder_synced_at is not None


def test_the_single_player_route_syncs_the_season_running_today(
    client: Client,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The route reads the matches of the season today sits in."""
    player = seeded["player_ids"][0]
    today = datetime.now(UTC).date()
    with Session() as session:
        user = session.get(User, player)
        user.battleTag = "thanks#11187"
        season = session.get(Season, seeded["season_id"])
        season.start_date = today - timedelta(days=1)
        season.end_date = today + timedelta(days=1)
        session.commit()
    serve(monkeypatch, {W3C_SEASON: THANKS[:2]})

    resp = client.post(f"/users/{player}/w3c-sync", headers=auth_headers)

    assert resp.status_code == 200
    assert len(stored()) == 2


def test_the_ladder_sync_route_answers_404_for_an_unknown_season(
    client: Client, auth_headers: dict[str, str]
) -> None:
    resp = client.post("/seasons/9999/ladder-sync", headers=auth_headers)

    assert resp.status_code == 404
    assert resp.json() == {"error": "Season not found"}
