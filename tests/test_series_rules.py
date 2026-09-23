"""A series knows its rules and its races with or without a fixture.

A GNL series reads them off the season of its fixture. A bracket series has
no fixture, so it reads the best-of off its round or its stage, the map rules
off its stage, and the race of each side off the event entrant row.
"""

from collections.abc import Callable
from typing import Any

from httpx2 import Client

from tests.test_stage_engine import cup, generate

ORDER = ["Ban_A", "Ban_B", "Pick_A", "Pick_B"]


def bracket_series(stage_id: int) -> dict[str, Any]:
    """The one series of a two entrant bracket, and the two players in it."""
    from sqlalchemy import select
    from sqlmodel import col

    from app.core.db import Session
    from app.models.base import ident
    from app.models.relationships import DBEventRound
    from app.models.series import Series
    from app.models.user import User

    with Session() as session:
        row = session.scalars(
            select(Series)
            .join(DBEventRound, col(DBEventRound.id) == col(Series.round_id))
            .where(col(DBEventRound.stage_id) == stage_id)
        ).one()
        players = {
            side: session.get(User, getattr(row, f"player{side}_id")) for side in (1, 2)
        }
        return {
            "id": ident(row),
            "discord": {
                side: player.discordId for side, player in players.items() if player
            },
        }


def event_pool(event_id: int, names: tuple[str, ...]) -> list[int]:
    """A map pool on the event, in pool order, and the ABBA veto order."""
    from app.core.db import Session
    from app.models.base import ident
    from app.models.map import Map
    from app.models.relationships import DBMapSeason
    from app.models.season import Season

    with Session.begin() as session:
        event = session.get(Season, event_id)
        assert event
        event.pick_ban = "|".join(ORDER)
        maps = [Map(name=short, shortname=short) for short in names]
        session.add_all(maps)
        session.flush()
        ids = [ident(row) for row in maps]
        session.add_all(
            [
                DBMapSeason(map_id=map_id, season_id=event_id, position=position)
                for position, map_id in enumerate(ids, start=1)
            ]
        )
        return ids


def test_a_bracket_series_reports_against_the_best_of_of_its_stage(
    client: Client,
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
    replay_uploaded: Callable[..., None],
) -> None:
    """The stage plays Bo1, so 1-0 lands and the Bo3 shape 2-0 is refused. A
    Bo3 stage would read the same as the default and prove nothing."""
    event, (stage,) = cup(2, best_of=1)
    generate(client, auth_headers, event, stage)
    series = bracket_series(stage)
    side_a = member(series["discord"][1])

    replay_uploaded(series["id"], 1, 2)
    long = client.put(
        f"/player-series/{series['id']}",
        headers=side_a,
        data={"action": "score_updated", "player1_score": "2", "player2_score": "0"},
    )
    assert long.status_code == 400, long.text
    assert long.json() == {"error": "A series of this season ends at 1 map wins."}

    resp = client.put(
        f"/player-series/{series['id']}",
        headers=side_a,
        data={"action": "score_updated", "player1_score": "1", "player2_score": "0"},
    )
    assert resp.status_code == 200, resp.text
    assert (resp.json()["player1_score"], resp.json()["player2_score"]) == (1, 0)


def test_a_round_best_of_overrides_the_one_of_its_stage(
    client: Client, auth_headers: dict[str, str]
) -> None:
    from sqlalchemy import select
    from sqlmodel import col

    from app.core.db import Session
    from app.models.relationships import DBEventRound

    event, (stage,) = cup(2, best_of=1)
    generate(client, auth_headers, event, stage)
    with Session.begin() as session:
        session.scalars(
            select(DBEventRound).where(col(DBEventRound.stage_id) == stage)
        ).one().best_of = 3

    resp = client.get(f"/events/{event}/stages/{stage}/series")
    assert resp.status_code == 200, resp.text
    assert resp.json()["series"][0]["rules"]["best_of"] == 3


def test_the_veto_board_of_a_bracket_series_reads_the_stage_rules(
    client: Client,
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
) -> None:
    """No fixture holds the series, so the board comes from the stage and the
    event pool, and a step taken by side A lands on it."""
    event, (stage,) = cup(2, best_of=3, map_rules="veto,loser,loser")
    generate(client, auth_headers, event, stage)
    pool = event_pool(event, ("EI", "TS", "LR", "AL", "CH"))
    series = bracket_series(stage)
    side_a = member(series["discord"][1])

    board = client.get(f"/player-series/{series['id']}/veto", headers=side_a)
    assert board.status_code == 200, board.text
    body = board.json()
    assert body["order"] == ORDER
    assert body["map_rules"] == "veto,loser,loser"
    assert body["pool"] == pool
    # No fixed rule, so no map is off the board before the veto starts
    assert body["week_map_id"] is None
    assert (body["viewer_side"], body["on_turn"]) == ("A", True)

    taken = client.put(
        f"/player-series/{series['id']}/veto",
        headers=side_a,
        json={"action": "step", "map_id": pool[0]},
    )
    assert taken.status_code == 200, taken.text
    assert [
        (step["side"], step["action"], step["map_id"]) for step in taken.json()["steps"]
    ] == [("A", "ban", pool[0])]


def test_the_stage_series_read_names_the_race_of_both_sides(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """A cup entrant has no season signup, so each race comes off its entrant row."""
    from sqlalchemy import select
    from sqlmodel import col

    from app.core.db import Session
    from app.models.enums import Race
    from app.models.event_entrant import EventEntrant

    event, (stage,) = cup(2)
    with Session.begin() as session:
        rows = session.scalars(
            select(EventEntrant)
            .where(col(EventEntrant.event_id) == event)
            .order_by(col(EventEntrant.seed))
        ).all()
        rows[0].race = Race.OC
        rows[1].race = Race.NE
    generate(client, auth_headers, event, stage)

    resp = client.get(f"/events/{event}/stages/{stage}/series")
    assert resp.status_code == 200, resp.text
    row = resp.json()["series"][0]
    assert (row["player1_race"], row["player2_race"]) == ("OC", "NE")
    assert row["rules"] == {"map_rules": "fixed,loser,loser", "best_of": 3}


def test_a_gnl_series_still_takes_its_rules_from_its_season(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The fixture names the season, so nothing about the GNL path changes."""
    resp = client.get(f"/series/{seeded['series_open_id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["rules"] == {"map_rules": "fixed,loser,loser", "best_of": 3}


def test_a_gnl_series_keeps_its_season_rules_under_a_backfilled_stage(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """The events migration gave every season a round robin stage holding a
    copy of its rules and pointed every round at it. A GNL series names no
    entrant, so it still prices on its season: a season re-priced on the
    Season Maps page reaches its series and its fixture score.
    """
    from sqlalchemy import select
    from sqlmodel import col

    from app.core.db import Session
    from app.models.base import ident
    from app.models.enums import StageFormat
    from app.models.event_stage import EventStage
    from app.models.relationships import DBEventRound
    from app.models.season import Season
    from app.models.series import Series

    season_id = seeded["season_id"]
    with Session.begin() as session:
        season = session.get(Season, season_id)
        assert season
        stage = EventStage(
            event_id=season_id,
            position=1,
            format=StageFormat.round_robin,
            best_of=3,
            map_rules=season.map_rules,
        )
        session.add(stage)
        session.flush()
        for round_ in session.scalars(
            select(DBEventRound).where(col(DBEventRound.season_id) == season_id)
        ):
            round_.stage_id = ident(stage)
        # A clean win prices 3 on the stale Bo3 and 2 on the season's Bo5
        played = session.get(Series, seeded["series_played_id"])
        assert played
        played.player2_score = 0

    rules = "veto,veto,veto,veto,veto"
    priced = client.put(
        f"/events/{season_id}", json={"map_rules": rules}, headers=auth_headers
    )
    assert priced.status_code == 200, priced.text

    resp = client.get(f"/series/{seeded['series_open_id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["rules"] == {"map_rules": rules, "best_of": 5}

    fixture = client.get(f"/matches/{seeded['match_id']}")
    assert fixture.status_code == 200, fixture.text
    assert (fixture.json()["team1_score"], fixture.json()["team2_score"]) == (2, 0)


def test_who_acts_for_a_side_of_a_series(seeded: dict[str, Any]) -> None:
    """One rule answers every route: the player a side names and the captains
    of the team that fields it act for it, a plain roster member does not, and
    a side that names no player is the team itself, so its roster acts."""
    from app.core.db import Session
    from app.models.base import ident
    from app.models.event_entrant import EventEntrant
    from app.models.relationships import DBTeamSeasonCaptain
    from app.models.series import Series
    from app.services.series_rules import acts_for_side

    season_id = seeded["season_id"]
    mate, named1, spare, named2 = seeded["player_ids"]
    with Session.begin() as session:
        sides = [
            EventEntrant(event_id=season_id, team_id=seeded[f"team_{key}_id"])
            for key in ("a", "b")
        ]
        session.add_all(sides)
        session.flush()
        series = session.get(Series, seeded["series_open_id"])
        assert series
        series.entrant1_id, series.entrant2_id = (ident(side) for side in sides)
        session.flush()

        assert acts_for_side(session, series, named1) == 1
        assert acts_for_side(session, series, named2) == 2
        # Each side names its player, so the rest of the roster stands outside
        assert acts_for_side(session, series, mate) is None
        assert acts_for_side(session, series, spare) is None

        session.add_all(
            [
                DBTeamSeasonCaptain(
                    team_id=seeded["team_a_id"], season_id=season_id, user_id=mate
                ),
                DBTeamSeasonCaptain(
                    team_id=seeded["team_b_id"], season_id=season_id, user_id=spare
                ),
            ]
        )
        session.flush()
        # A captain acts for the side its own team fields, never the other one
        assert acts_for_side(session, series, mate) == 1
        assert acts_for_side(session, series, spare) == 2

        # The team stands on side 2 itself once no player is named for it
        series.player2_id = None
        session.flush()
        assert acts_for_side(session, series, named2) == 2
