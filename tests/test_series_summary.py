"""The summary list of an event's fixture series against the detail list.

GET /events/{event_id}/series answers SeriesPublic, the detail; the summary
list answers the same fixture series as flat rows. The detail is the oracle:
every field the summary carries equals the same field of the detail row.

Parity holds for valid scores only. points() raises on a score a series cannot
end on, where the summary's points_case answers one, so the seeded scores are
all valid.
"""

from typing import Any

import pytest
from httpx2 import Client
from sqlalchemy import select
from sqlmodel import col

from app.core.db import Session
from app.models.base import ident
from app.models.enums import Race
from app.models.event_entrant import EventEntrant
from app.models.match import Match
from app.models.relationships import DBEventRound, DBUserSeasonSignup
from app.models.series import Series
from app.models.series_cast import SeriesCast


@pytest.fixture
def season(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> dict[str, Any]:
    """The seeded season with an off-race row, a walkover, three casts and two
    series that are not fixture series: one names entrants, one has no match."""
    p1, p2, p3, p4 = seeded["player_ids"]
    with Session.begin() as session:
        session.add_all(
            DBUserSeasonSignup(
                user_id=user_id, season_id=seeded["season_id"], race=race
            )
            for user_id, race in zip(
                seeded["player_ids"], (Race.HU, Race.OC, Race.NE, Race.UD), strict=True
            )
        )
        played = session.get_one(Series, seeded["series_played_id"])
        played.player1_off_race = Race.OC
        second = Match(
            team1_id=seeded["team_b_id"],
            team2_id=seeded["team_a_id"],
            season_id=seeded["season_id"],
            playday=2,
        )
        session.add(second)
        session.flush()
        walkover = Series(
            match_id=ident(second), player1_id=p3, player2_id=p1, host_player_id=p3
        )
        fantasy = Series(
            match_id=ident(second),
            player1_id=p4,
            player2_id=p2,
            host_player_id=p4,
            is_fantasy_match=True,
        )
        entrants = [
            EventEntrant(
                event_id=seeded["season_id"], user_id=user_id, race=Race.RANDOM
            )
            for user_id in (p2, p4)
        ]
        session.add_all([walkover, fantasy, *entrants])
        session.flush()
        staged = Series(
            match_id=ident(second),
            player1_id=p2,
            player2_id=p4,
            entrant1_id=ident(entrants[0]),
            entrant2_id=ident(entrants[1]),
            player1_score=2,
            player2_score=0,
            host_player_id=p2,
        )
        round_id = session.scalars(
            select(col(DBEventRound.id)).where(
                col(DBEventRound.season_id) == seeded["season_id"]
            )
        ).first()
        unfixed = Series(
            round_id=round_id, player1_id=p1, player2_id=p3, host_player_id=p1
        )
        session.add_all([staged, unfixed])
        session.add_all(
            [
                SeriesCast(
                    series_id=seeded["series_played_id"],
                    user_id=p2,
                    channel_url="https://twitch.tv/p2",
                ),
                # A video claimed as the channel is its own VOD once scored
                SeriesCast(
                    series_id=seeded["series_played_id"],
                    channel_url="https://www.youtube.com/watch?v=abc",
                ),
                SeriesCast(
                    series_id=seeded["series_open_id"],
                    channel_url="https://www.youtube.com/watch?v=def",
                    vod_url="https://youtu.be/xyz",
                ),
            ]
        )
        session.flush()
        ids = {
            "walkover_id": ident(walkover),
            "staged_id": ident(staged),
            "unfixed_id": ident(unfixed),
            "second_match_id": ident(second),
        }
    scored = client.put(
        f"/series/{ids['walkover_id']}/result-kind",
        json={"result_kind": "walkover", "winner": 2},
        headers=auth_headers,
    )
    assert scored.status_code == 200, scored.text
    return seeded | ids


def summary_of(detail: dict[str, Any]) -> dict[str, Any]:
    """The summary fields of one detail row, as the detail answers them."""

    def player(side: int) -> dict[str, Any] | None:
        found = detail[f"player{side}"]
        if found is None:
            return None
        race = detail[f"player{side}_race"]
        return {"id": found["id"], "name": found["name"], "race": race}

    return {
        "id": detail["id"],
        "season_id": detail["match"]["season_id"],
        "match_id": detail["match_id"],
        "week": detail["match"]["playday"],
        "date_time": detail["date_time"],
        "player1": player(1),
        "player2": player(2),
        "player1_score": detail["player1_score"],
        "player2_score": detail["player2_score"],
        "player1_points": detail["player1_points"],
        "player2_points": detail["player2_points"],
        "casts": [
            {key: cast[key] for key in ("id", "name", "channel_url", "vod_url")}
            for cast in sorted(detail["casts"], key=lambda cast: cast["id"])
        ],
    }


def fixture_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The detail rows that are fixture series: a match and no entrant."""
    return [
        row
        for row in rows
        if row["match_id"] is not None
        and row.get("entrant1_id") is None
        and row.get("entrant2_id") is None
    ]


def test_the_summary_equals_the_detail_on_every_fixture_series(
    client: Client, season: dict[str, Any]
) -> None:
    base = f"/events/{season['season_id']}/series"
    detail = client.get(base)
    summary = client.get(f"{base}/summary")
    assert detail.status_code == summary.status_code == 200
    assert summary.headers["Cache-Control"] == detail.headers["Cache-Control"]
    expected = [summary_of(row) for row in fixture_rows(detail.json())]
    assert summary.json() == expected
    rows = {row["id"]: row for row in summary.json()}
    # The walkover, the off race and both cast rules are in the compared rows
    assert rows[season["walkover_id"]]["player2_points"] == 3
    played = rows[season["series_played_id"]]
    assert played["player1"]["race"] == "OC"
    assert [cast["vod_url"] for cast in played["casts"]] == [
        None,
        "https://www.youtube.com/watch?v=abc",
    ]
    assert played["casts"][0]["name"] == "P2"
    assert rows[season["series_open_id"]]["casts"][0]["vod_url"] == (
        "https://youtu.be/xyz"
    )


def test_a_stage_or_round_series_is_not_a_summary_row(
    client: Client, season: dict[str, Any]
) -> None:
    base = f"/events/{season['season_id']}/series"
    detail_ids = {row["id"] for row in client.get(base).json()}
    summary_ids = {row["id"] for row in client.get(f"{base}/summary").json()}
    assert season["staged_id"] in detail_ids
    assert {season["staged_id"], season["unfixed_id"]}.isdisjoint(summary_ids)


@pytest.mark.parametrize(
    "query",
    [
        "player_id={p1}",
        "team_id={team_a_id}",
        "match_id={second_match_id}",
        "is_fantasy_match=true",
        "is_fantasy_match=false",
        "limit=2&offset=1",
    ],
)
def test_the_filters_and_the_order_are_those_of_the_detail(
    client: Client, season: dict[str, Any], query: str
) -> None:
    """The same filters keep the same fixture series, in id order."""
    base = f"/events/{season['season_id']}/series"
    query = query.format(p1=season["player_ids"][0], **season)
    if query.startswith("limit"):
        # The detail pages over every series, so compare against all of them
        expected = [row["id"] for row in fixture_rows(client.get(base).json())][1:3]
    else:
        expected = [
            row["id"] for row in fixture_rows(client.get(f"{base}?{query}").json())
        ]
    found = [row["id"] for row in client.get(f"{base}/summary?{query}").json()]
    assert found == expected
    assert found


def test_a_missing_event_answers_an_empty_list(client: Client) -> None:
    response = client.get("/events/987654/series/summary")
    assert response.status_code == 200
    assert response.json() == []
