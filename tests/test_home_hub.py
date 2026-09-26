"""The home hub read: three short series lists of every event kind in one answer.

`GET /home/series` needs no token. It answers what is booked next, what a
caster claimed, and what was cast and has a VOD. A draft pairing and an
unpublished event never ride in it, and the answer stays small enough to
travel on every visit to the home page.
"""

import gzip
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
from app.models.match import Match
from app.models.relationships import DBEventRound, DBUserSeasonSignup
from app.models.season import Season
from app.models.series import Series
from app.models.series_cast import SeriesCast
from app.models.team import Team
from app.models.types import utcnow
from app.models.user import User
from app.models.w3c_stats import W3CStats
from tests.test_query_budget import count_statements

VOD = "https://www.twitch.tv/videos/12345"
CHANNEL = "https://www.twitch.tv/gnlcaster"

# The wire body of every home page visit stays under this; the raw body is larger
EGRESS_CEILING = 4096
# A new field on a row shows here first, before the edge compresses the answer
RAW_CEILING = 8192


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


def icon(index: int) -> str:
    """A team icon URL of the length the blob store writes, about ninety characters."""
    return (
        "https://q7w2x9k4m1n8p3v6.public.blob.vercel-storage.com"
        f"/team-icons/team-{index:02d}-Ab3xK9zQ2w6tYu.png"
    )


def fixture_series(
    session: OrmSession,
    seeded: dict[str, Any],
    *,
    index: int,
    players: tuple[int, int],
    when: datetime,
    scored: bool,
) -> Series:
    """One GNL fixture of two teams of its own, each with an icon, and its series."""
    teams = [
        Team(
            name=f"Tower Rush {index * 2 + side}",
            league_id=seeded["league_id"],
            icon_url=icon(index * 2 + side),
        )
        for side in (0, 1)
    ]
    session.add_all(teams)
    session.flush()
    match = Match(
        team1_id=ident(teams[0]),
        team2_id=ident(teams[1]),
        season_id=seeded["season_id"],
        playday=index % 4 + 1,
    )
    session.add(match)
    session.flush()
    series = Series(
        match_id=ident(match),
        player1_id=players[0],
        player2_id=players[1],
        host_player_id=players[0],
        date_time=when,
        player1_score=2 if scored else None,
        player2_score=1 if scored else None,
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
        # the GNL season runs, so its rows read the current rating
        season = session.get(Season, seeded["season_id"])
        assert season is not None
        season.end_date = (now + timedelta(days=30)).date()
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
    # The label in parts, the fixture teams, and no key at all for an empty field
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
        # The channel-only claim is written first, so a fallback names the wrong caster
        session.add_all(
            [
                SeriesCast(
                    series_id=hub["series_played_id"],
                    user_id=hub["player_ids"][1],
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
        # A played series whose only claim holds no VOD is not a recent cast
        channel_only = fixture_series(
            session,
            hub,
            index=9,
            players=(hub["player_ids"][0], hub["player_ids"][2]),
            when=hub["now"] - timedelta(days=1),
            scored=True,
        )
        session.add(
            SeriesCast(
                series_id=ident(channel_only),
                user_id=hub["player_ids"][0],
                channel_url=CHANNEL,
            )
        )
        session.commit()

    body = read(client)
    # The channel-only series is newer, so it would sort first if it rode at all
    assert [row["id"] for row in body["casts_recent"]] == [hub["series_played_id"]]
    row = body["casts_recent"][0]
    assert (row["player1_score"], row["player2_score"]) == (2, 1)
    assert row["cast"] == {"name": "P1", "url": VOD}
    assert hub["series_played_id"] not in [next_row["id"] for next_row in body["next"]]


def test_a_started_series_holds_its_place_for_two_hours(
    client: Client, hub: dict[str, Any]
) -> None:
    """The booked lists keep a series two hours past its start, so a cast that
    is live right now still has a card. A result drops it at once."""
    now = hub["now"]
    first, second, third, fourth = hub["player_ids"]
    with Session() as session:
        live = event_with_series(
            session,
            name="Live Cup",
            short_name="LC",
            kind=EventKind.cup,
            stage_name=None,
            round_name=None,
            players=(first, second),
            when=now - timedelta(hours=1),
        )
        stale = event_with_series(
            session,
            name="Stale Cup",
            short_name="SC",
            kind=EventKind.cup,
            stage_name=None,
            round_name=None,
            players=(first, third),
            when=now - timedelta(hours=3),
        )
        scored = event_with_series(
            session,
            name="Scored Cup",
            short_name="CC",
            kind=EventKind.cup,
            stage_name=None,
            round_name=None,
            players=(second, fourth),
            when=now - timedelta(hours=1),
        )
        scored.player1_score, scored.player2_score = 2, 0
        session.add(
            SeriesCast(series_id=ident(live), user_id=first, channel_url=CHANNEL)
        )
        session.commit()
        live_id, stale_id, scored_id = ident(live), ident(stale), ident(scored)

    body = read(client)
    ids = [row["id"] for row in body["next"]]
    # Soonest first, so the series that already started leads the list
    assert ids[0] == live_id
    assert stale_id not in ids
    assert scored_id not in ids
    assert [row["id"] for row in body["casts_upcoming"]] == [live_id]


def test_an_empty_database_answers_three_empty_lists(client: Client) -> None:
    assert read(client) == {"next": [], "casts_upcoming": [], "casts_recent": []}


def test_the_hub_read_is_cacheable_at_the_edge(
    client: Client, hub: dict[str, Any]
) -> None:
    resp = client.get("/home/series")
    assert resp.headers["cache-control"] == (
        "public, s-maxage=120, stale-while-revalidate=600"
    )
    # this client sends no Origin, and the copy the edge stores must still read in a browser
    assert resp.headers["access-control-allow-origin"] == "*"


def test_the_hub_costs_a_fixed_number_of_statements(
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
    # one of them tells the running events from the finished ones
    assert tally[0] == 16


def test_the_worst_case_answer_stays_under_the_egress_ceiling(
    client: Client, seeded: dict[str, Any]
) -> None:
    """Every list at its cap and every row the longest kind there is.

    A GNL fixture row is the worst case: it carries two teams on top of what a
    cup row holds, each with an icon URL of the length the blob store writes.
    Nine fixtures fill the three lists with twelve rows, and no two of them
    share a team, so nothing in the answer repeats.
    """
    now = utcnow()
    first, second, third, fourth = seeded["player_ids"]
    with Session() as session:
        # Names of the length players and teams really use
        for index, user_id in enumerate(seeded["player_ids"]):
            player = session.get(User, user_id)
            assert player is not None
            player.name = f"Contender{index:02d}"
            session.add(
                DBUserSeasonSignup(
                    user_id=user_id, season_id=seeded["season_id"], race=Race.OC
                )
            )
            session.add(
                W3CStats(user_id=user_id, race=Race.OC, wc3_season=20, mmr=1400 + index)
            )
        for index in range(9):
            booked = index < 5
            row = fixture_series(
                session,
                seeded,
                index=index,
                players=(first, third) if booked else (second, fourth),
                when=now + timedelta(hours=index + 1)
                if booked
                else now - timedelta(days=index),
                scored=not booked,
            )
            # Three of the booked rows are claimed, and every played one has a VOD
            if booked and index < 3:
                session.add(
                    SeriesCast(series_id=ident(row), user_id=first, channel_url=CHANNEL)
                )
            if not booked:
                session.add(
                    SeriesCast(
                        series_id=ident(row),
                        user_id=first,
                        channel_url=CHANNEL,
                        vod_url=VOD,
                    )
                )
        session.commit()

    answer = read(client)
    assert [len(answer[key]) for key in answer] == [5, 3, 4]
    body = json.dumps(answer, separators=(",", ":")).encode()
    # The edge and every browser speak gzip, so the packed body is what crosses the wire
    packed = gzip.compress(body)
    assert len(packed) < EGRESS_CEILING, (len(body), len(packed))
    assert len(body) < RAW_CEILING, len(body)
