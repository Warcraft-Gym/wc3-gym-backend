"""The home hub read: three short series lists of every event kind in one answer.

`GET /home/series` needs no token. It answers what is booked next, what a
caster claimed, and what was cast and has a VOD. A draft pairing and an
unpublished event never ride in it, and the answer stays small enough to
travel on every visit to the home page.
"""

import json
from datetime import datetime, timedelta
from typing import Any

import pytest
from httpx2 import Client
from sqlalchemy.orm import Session as OrmSession

from app.core.db import Session
from app.models.base import ident
from app.models.draft_series import DraftSeries
from app.models.enums import EntrantKind, EventKind, LeagueKind, Race, StageFormat
from app.models.event_stage import EventStage
from app.models.league import League
from app.models.relationships import DBEventRound, DBUserSeasonSignup
from app.models.season import Season
from app.models.series import Series
from app.models.series_cast import SeriesCast
from app.models.types import utcnow
from app.models.w3c_stats import W3CStats
from tests.test_query_budget import count_statements

VOD = "https://www.twitch.tv/videos/12345"
CHANNEL = "https://www.twitch.tv/gnlcaster"

# The answer rides on every home page visit, so it stays under this
EGRESS_CEILING = 4096


def event_with_series(
    session: OrmSession,
    *,
    name: str,
    short_name: str,
    kind: EventKind,
    stage_name: str | None,
    round_name: str | None,
    players: tuple[int, int],
    when: datetime,
    published: bool = True,
) -> Series:
    """One event of its own league, with one stage, one round and one series.

    The series names no fixture, the way a cup or a KOTH night plays it.
    """
    league = League(
        name=f"{name} League", short_name=short_name, kind=LeagueKind.custom
    )
    session.add(league)
    session.flush()
    event = Season(
        name=name,
        league_id=ident(league),
        kind=kind,
        entrant_kind=EntrantKind.solo,
        series_per_round=1,
        published=published,
    )
    session.add(event)
    session.flush()
    stage = EventStage(
        event_id=ident(event),
        position=1,
        name=stage_name,
        format=StageFormat.single_elimination,
    )
    session.add(stage)
    session.flush()
    round_row = DBEventRound(
        stage_id=ident(stage), season_id=ident(event), number=2, name=round_name
    )
    session.add(round_row)
    session.flush()
    series = Series(
        round_id=ident(round_row),
        player1_id=players[0],
        player2_id=players[1],
        host_player_id=players[0],
        date_time=when,
    )
    session.add(series)
    session.flush()
    return series


@pytest.fixture
def hub(seeded: dict[str, Any]) -> dict[str, Any]:
    """A GNL series, a cup series and a KOTH series booked in that order.

    The GNL players hold a season signup and a W3C rating, so their row names
    a race and a rating.
    """
    now = utcnow()
    first, second, third, fourth = seeded["player_ids"]
    with Session() as session:
        gnl = session.get(Series, seeded["series_open_id"])
        assert gnl is not None
        gnl.date_time = now + timedelta(hours=1)
        session.add_all(
            DBUserSeasonSignup(
                user_id=user_id, season_id=seeded["season_id"], race=race
            )
            for user_id, race in ((second, Race.OC), (fourth, Race.UD))
        )
        session.add_all(
            [
                W3CStats(user_id=second, race=Race.OC, wc3_season=20, mmr=1400),
                W3CStats(user_id=fourth, race=Race.UD, wc3_season=20, mmr=1300),
            ]
        )
        cup = event_with_series(
            session,
            name="Autumn Cup",
            short_name="W3C",
            kind=EventKind.cup,
            stage_name="Group stage",
            round_name=None,
            players=(first, third),
            when=now + timedelta(hours=2),
        )
        koth = event_with_series(
            session,
            name="Weekly KOTH",
            short_name="KOTH",
            kind=EventKind.koth,
            stage_name=None,
            round_name="Bracket A",
            players=(first, fourth),
            when=now + timedelta(hours=3),
        )
        session.commit()
        ids = {"cup_series_id": ident(cup), "koth_series_id": ident(koth)}
    return {**seeded, **ids, "now": now}


def read(client: Client) -> dict[str, Any]:
    resp = client.get("/home/series")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_hub_answers_every_event_kind_in_time_order(
    client: Client, hub: dict[str, Any]
) -> None:
    body = read(client)
    rows = body["next"]
    assert [row["id"] for row in rows] == [
        hub["series_open_id"],
        hub["cup_series_id"],
        hub["koth_series_id"],
    ]

    gnl, cup, koth = rows
    # The context label in parts, and the fixture teams of a league series
    # An empty field is left out of the row, so a reader defaults it
    assert (gnl["league"], gnl["event"], gnl.get("stage"), gnl["round"]) == (
        "SL",
        "Season 1",
        None,
        "Round 1",
    )
    assert (gnl["team1"]["name"], gnl["team2"]["name"]) == ("Alpha", "Beta")
    assert (cup["league"], cup["event"], cup["stage"], cup["round"]) == (
        "W3C",
        "Autumn Cup",
        "Group stage",
        "Round 2",
    )
    assert (koth.get("stage"), koth["round"]) == (None, "Bracket A")
    # A series the entrants play themselves names no team
    assert "team1" not in cup and "team2" not in cup

    # One player shape: id, name, country, the race the row names, one rating
    assert gnl["player1"] == {
        "id": hub["player_ids"][1],
        "name": "P2",
        "country": "US",
        "race": "OC",
        "mmr": 1400,
    }
    assert gnl["player2"]["mmr"] == 1300
    assert "player1_score" not in gnl
    assert "cast" not in gnl


def test_a_draft_pairing_and_an_unpublished_event_never_show(
    client: Client, hub: dict[str, Any]
) -> None:
    now = hub["now"]
    first, second, third, _ = hub["player_ids"]
    with Session() as session:
        session.add(
            DraftSeries(
                match_id=hub["match_id"],
                date_time=now + timedelta(minutes=5),
                player1_id=first,
                player2_id=third,
                host_player_id=first,
            )
        )
        event_with_series(
            session,
            name="Hidden Cup",
            short_name="HC",
            kind=EventKind.cup,
            stage_name=None,
            round_name=None,
            players=(first, second),
            when=now + timedelta(minutes=10),
            published=False,
        )
        session.commit()

    # Both would sort ahead of every booked series, and neither is in the answer
    assert [row["id"] for row in read(client)["next"]] == [
        hub["series_open_id"],
        hub["cup_series_id"],
        hub["koth_series_id"],
    ]


def test_a_claimed_series_rides_in_casts_upcoming(
    client: Client, hub: dict[str, Any]
) -> None:
    with Session() as session:
        session.add(
            SeriesCast(
                series_id=hub["cup_series_id"],
                user_id=hub["player_ids"][0],
                channel_url=CHANNEL,
            )
        )
        session.commit()

    body = read(client)
    (row,) = body["casts_upcoming"]
    assert row["id"] == hub["cup_series_id"]
    assert row["cast"] == {"name": "P1", "url": CHANNEL}
    # The same series still sits in the next list, with the same cast
    assert body["next"][1]["cast"]["url"] == CHANNEL
    assert body["casts_recent"] == []


def test_a_finished_casted_series_shows_with_its_score(
    client: Client, hub: dict[str, Any]
) -> None:
    with Session() as session:
        # A claim with no VOD is not a recent cast, and a played series is not next
        session.add_all(
            [
                SeriesCast(
                    series_id=hub["series_played_id"],
                    user_id=hub["player_ids"][0],
                    channel_url=CHANNEL,
                    vod_url=VOD,
                ),
                SeriesCast(
                    series_id=hub["series_played_id"],
                    user_id=hub["player_ids"][1],
                    channel_url=CHANNEL,
                ),
            ]
        )
        session.commit()

    body = read(client)
    (row,) = body["casts_recent"]
    assert row["id"] == hub["series_played_id"]
    assert (row["player1_score"], row["player2_score"]) == (2, 1)
    assert row["cast"] == {"name": "P1", "url": VOD}
    assert hub["series_played_id"] not in [next_row["id"] for next_row in body["next"]]


def test_an_empty_database_answers_three_empty_lists(client: Client) -> None:
    assert read(client) == {"next": [], "casts_upcoming": [], "casts_recent": []}


def test_the_hub_read_is_cacheable_at_the_edge(
    client: Client, hub: dict[str, Any]
) -> None:
    resp = client.get("/home/series")
    assert resp.headers["cache-control"] == "public, s-maxage=120"
    # this client sends no Origin, the shape of a fill by curl or a bot. The copy the
    # edge stores must still let a browser read it.
    assert resp.headers["access-control-allow-origin"] == "*"


def test_the_hub_costs_a_fixed_number_of_statements_and_stays_small(
    client: Client, hub: dict[str, Any]
) -> None:
    """Three list statements, their two collection loads each, and one pass
    that names and rates every side. None of them grows with the rows."""
    from app.services import home

    with Session() as session:
        session.add_all(
            [
                SeriesCast(
                    series_id=hub["cup_series_id"],
                    user_id=hub["player_ids"][0],
                    channel_url=CHANNEL,
                ),
                SeriesCast(
                    series_id=hub["series_played_id"],
                    user_id=hub["player_ids"][0],
                    channel_url=CHANNEL,
                    vod_url=VOD,
                ),
            ]
        )
        session.commit()

    with count_statements() as tally:
        answer = home.series()
    assert len(answer.next) == 3
    assert tally[0] == 15


def test_a_full_answer_stays_under_the_egress_ceiling(
    client: Client, hub: dict[str, Any]
) -> None:
    """Every list at its cap: five booked, three of them claimed, four VODs."""
    now = hub["now"]
    first, second, third, fourth = hub["player_ids"]
    with Session() as session:
        team = session.get(Season, hub["season_id"])
        assert team is not None
        for index in range(4):
            booked = event_with_series(
                session,
                name=f"Autumn Cup {index}",
                short_name="W3C",
                kind=EventKind.cup,
                stage_name="Group stage",
                round_name="Quarter final",
                players=(first, third),
                when=now + timedelta(hours=4 + index),
            )
            played = event_with_series(
                session,
                name=f"Spring Cup {index}",
                short_name="W3C",
                kind=EventKind.cup,
                stage_name="Group stage",
                round_name="Quarter final",
                players=(second, fourth),
                when=now - timedelta(days=index + 1),
            )
            played.player1_score, played.player2_score = 2, 1
            session.add(
                SeriesCast(
                    series_id=ident(played),
                    user_id=first,
                    channel_url=CHANNEL,
                    vod_url=VOD,
                )
            )
            if index < 2:
                session.add(
                    SeriesCast(
                        series_id=ident(booked), user_id=first, channel_url=CHANNEL
                    )
                )
        session.add(
            SeriesCast(
                series_id=hub["cup_series_id"], user_id=first, channel_url=CHANNEL
            )
        )
        session.commit()

    answer = read(client)
    assert [len(answer[key]) for key in answer] == [5, 3, 4]
    body = json.dumps(answer, separators=(",", ":"))
    assert len(body) < EGRESS_CEILING, len(body)
