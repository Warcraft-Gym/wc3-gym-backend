"""A player's summary, seasons, series and career row answer what the wider
reads answer.

Each read is checked against the route it replaces on the same rows:
/users/{id} for the summary, /users/{id} gnl_stats and signup_seasons with
/users/{id}/history captain_of for the seasons, /events/{id}/series?player_id=
for the series, and the /stats/career list for the career row.
"""

from datetime import UTC, date, datetime
from typing import Any

import pytest
from httpx2 import Client
from sqlalchemy import delete, select
from sqlmodel import col

from app.core.db import Session
from app.models.base import ident
from app.models.enums import Race
from app.models.match import Match
from app.models.relationships import (
    DBEventRound,
    DBTeamSeasonCaptain,
    DBUserSeasonSignup,
)
from app.models.series import Series
from app.models.series_cast import SeriesCast
from app.models.settings import Settings
from app.models.team_season import DBTeamSeason
from app.models.user import User
from app.models.user_battle_tag import UserBattleTag
from app.models.user_team_season import DBUserTeamSeason
from app.models.w3c_stats import W3CStats
from app.services.w3c_stats import W3C_SEASON_KEY
from tests.seed import active, add_season
from tests.test_mmr_summary import stats as ladder  # noqa: F401  # fixture


@pytest.fixture
def league(seeded: dict[str, Any]) -> dict[str, Any]:
    """The seeded league plus a later season, a captain-only season, signups,
    an off race, casts, and a bracket series outside any fixture.

    P1 plays team A in season 1 and captains it; in season 2 he plays and
    captains team B; in season 3 he only captains team A."""
    p1, p2, p3, p4 = seeded["player_ids"]
    team_a, team_b = seeded["team_a_id"], seeded["team_b_id"]
    first = seeded["season_id"]
    with Session.begin() as session:
        second = add_season(
            session,
            2,
            name="Season 2",
            league_id=seeded["league_id"],
            series_per_round=2,
            start_date=date(2026, 4, 6),
        )
        third = add_season(
            session,
            2,
            name="Season 3",
            league_id=seeded["league_id"],
            series_per_round=2,
            start_date=date(2026, 7, 6),
        )
        second_id, third_id = ident(second), ident(third)
        session.add_all(
            [
                DBTeamSeason(team_id=team_a, season_id=second_id),
                DBTeamSeason(team_id=team_b, season_id=second_id),
                DBTeamSeasonCaptain(team_id=team_a, season_id=first, user_id=p1),
                DBUserTeamSeason(user_id=p1, team_id=team_b, season_id=second_id),
                DBUserTeamSeason(user_id=p2, team_id=team_a, season_id=second_id),
                DBUserTeamSeason(user_id=p4, team_id=team_a, season_id=second_id),
                DBTeamSeasonCaptain(team_id=team_b, season_id=second_id, user_id=p1),
                DBTeamSeasonCaptain(team_id=team_a, season_id=third_id, user_id=p1),
                DBUserSeasonSignup(
                    user_id=p1, season_id=first, race=Race.HU, played_as="P1#0001"
                ),
                DBUserSeasonSignup(user_id=p3, season_id=first, race=Race.NE),
                DBUserSeasonSignup(user_id=p1, season_id=second_id, race=Race.OC),
                DBUserSeasonSignup(user_id=p2, season_id=second_id, race=Race.UD),
                SeriesCast(
                    series_id=seeded["series_played_id"],
                    channel_url="https://twitch.tv/first",
                ),
                SeriesCast(
                    series_id=seeded["series_played_id"],
                    channel_url="https://twitch.tv/second",
                    vod_url="https://twitch.tv/videos/123",
                    user_id=p2,
                ),
            ]
        )
        week2 = Match(team1_id=team_b, team2_id=team_a, season_id=second_id, playday=2)
        week1 = Match(team1_id=team_a, team2_id=team_b, season_id=second_id, playday=1)
        session.add_all([week2, week1])
        session.flush()
        late = Series(
            match_id=ident(week2),
            date_time=datetime(2026, 4, 15, 19, 0, tzinfo=UTC),
            player1_id=p1,
            player2_id=p4,
            host_player_id=p1,
        )
        early = Series(
            match_id=ident(week1),
            date_time=datetime(2026, 4, 8, 19, 0, tzinfo=UTC),
            player1_id=p2,
            player2_id=p1,
            player1_score=0,
            player2_score=2,
            player2_off_race=Race.RANDOM,
            host_player_id=p2,
        )
        session.add_all([late, early])
        round_id = session.scalars(
            select(col(DBEventRound.id)).where(col(DBEventRound.season_id) == first)
        ).first()
        session.add(
            Series(
                round_id=round_id,
                player1_id=p1,
                player2_id=p3,
                player1_score=2,
                player2_score=0,
                host_player_id=p1,
            )
        )
        session.flush()
        ids = {
            "second_id": second_id,
            "third_id": third_id,
            "late_id": ident(late),
            "early_id": ident(early),
        }
    return {**seeded, **ids}


def test_seasons_answer_what_the_user_and_history_reads_answer(
    client: Client, league: dict[str, Any]
) -> None:
    for user_id in league["player_ids"]:
        user = client.get(f"/users/{user_id}").json()
        captain_of = client.get(f"/users/{user_id}/history").json()["captain_of"]
        resp = client.get(f"/users/{user_id}/seasons")
        assert resp.status_code == 200
        seasons = resp.json()

        stats = {stat["season_id"]: stat for stat in user["gnl_stats"]}
        signups = {row["id"]: row for row in user["signup_seasons"]}
        captained = {(seat["season_id"], seat["team_id"]) for seat in captain_of}
        assert {row["season_id"] for row in seasons} == set(stats) | {
            season_id for season_id, _ in captained
        }
        for row in seasons:
            season_id, team_id = row["season_id"], row["team"]["id"]
            stat = stats.get(season_id)
            assert row["captain_only"] == (stat is None)
            assert team_id == (stat["team_id"] if stat else team_id)
            assert row["is_captain"] == ((season_id, team_id) in captained)
            record = {key: row["record"][key] for key in ("games", "wins", "losses")}
            if stat:
                assert record == {key: stat[key] for key in record}
                assert row["record"]["matchup_history"] == stat["matchup_history"]
            signup = signups.get(season_id)
            assert row["signup_race"] == (signup["signup_race"] if signup else None)
            assert row["played_as"] == (signup["played_as"] if signup else None)


def test_seasons_read_newest_first_with_the_team_summary(
    client: Client, league: dict[str, Any]
) -> None:
    seasons = client.get(f"/users/{league['player_ids'][0]}/seasons").json()
    assert [row["season_id"] for row in seasons] == [
        league["third_id"],
        league["second_id"],
        league["season_id"],
    ]
    third, second, first = seasons
    assert third["captain_only"] and third["is_captain"]
    assert third["team"]["id"] == league["team_a_id"]
    assert third["record"] == {
        "games": 0,
        "wins": 0,
        "losses": 0,
        "matchup_history": [],
    }
    assert second["team"] == {
        "id": league["team_b_id"],
        "league_id": league["league_id"],
        "name": "Beta",
        "long_name": "Team Beta",
        "icon_url": None,
    }
    assert second["is_captain"] and not second["captain_only"]
    assert second["signup_race"] == "OC"
    assert second["record"] == {
        "games": 2,
        "wins": 1,
        "losses": 0,
        "matchup_history": ["UD", None],
    }
    assert first["is_captain"] and first["played_as"] == "P1#0001"
    assert first["record"]["matchup_history"] == ["NE"]


def test_an_unknown_player_has_no_seasons(
    client: Client, league: dict[str, Any]
) -> None:
    resp = client.get("/users/999999/seasons")
    assert resp.status_code == 200
    assert resp.json() == []


def test_series_answer_what_the_event_series_read_answers(
    client: Client, league: dict[str, Any]
) -> None:
    events = [league["season_id"], league["second_id"]]
    for user_id in league["player_ids"]:
        wide = {
            row["id"]: row
            for event_id in events
            for row in client.get(
                f"/events/{event_id}/series?player_id={user_id}"
            ).json()
            if row["match_id"] is not None
        }
        query = "&".join(f"event_id={event_id}" for event_id in events)
        resp = client.get(f"/users/{user_id}/series?{query}")
        assert resp.status_code == 200
        slim = resp.json()
        assert {row["id"] for row in slim} == set(wide)
        assert resp.headers["x-total-count"] == str(len(slim))
        for row in slim:
            full = wide[row["id"]]
            mine, theirs = ("1", "2") if full["player1_id"] == user_id else ("2", "1")
            match = full["match"]
            assert row["season_id"] == match["season_id"]
            assert row["week"] == match["playday"]
            assert row["date_time"] == full["date_time"]
            assert row["race"] == full[f"player{mine}_race"]
            assert row["opponent_race"] == full[f"player{theirs}_race"]
            assert row["score"] == full[f"player{mine}_score"]
            assert row["opponent_score"] == full[f"player{theirs}_score"]
            assert row["opponent_id"] == full[f"player{theirs}_id"]
            assert row["opponent_name"] == full[f"player{theirs}"]["name"]
            for side in ("team1", "team2"):
                team = match[side]
                assert row[f"{side}_name"] == (team["long_name"] or team["name"])
            casts = full["casts"]
            cast = next((one for one in casts if one["vod_url"]), None) or (
                casts[0] if casts else None
            )
            assert row["cast_id"] == (cast["id"] if cast else None)
            assert row["cast_name"] == (cast["name"] if cast else None)
            assert row["cast_channel_url"] == (cast["channel_url"] if cast else None)
            assert row["cast_vod_url"] == (cast["vod_url"] if cast else None)


def test_series_read_by_season_week_and_time_and_page(
    client: Client, league: dict[str, Any]
) -> None:
    p1 = league["player_ids"][0]
    query = f"event_id={league['second_id']}&event_id={league['season_id']}"
    rows = client.get(f"/users/{p1}/series?{query}").json()
    assert [row["id"] for row in rows] == [
        league["series_played_id"],
        league["early_id"],
        league["late_id"],
    ]
    first = rows[0]
    assert first["cast_name"] == "P2"
    assert first["cast_vod_url"] == "https://twitch.tv/videos/123"
    early = rows[1]
    assert (early["race"], early["opponent_race"]) == ("RANDOM", "UD")
    assert (early["score"], early["opponent_score"]) == (2, 0)
    assert early["team1_name"] == "Team Alpha"

    paged = []
    for offset in range(3):
        resp = client.get(f"/users/{p1}/series?{query}&limit=1&offset={offset}")
        assert resp.headers["x-total-count"] == "3"
        paged += [row["id"] for row in resp.json()]
    assert paged == [row["id"] for row in rows]
    past = client.get(f"/users/{p1}/series?{query}&offset=5")
    assert past.json() == []
    assert past.headers["x-total-count"] == "3"


def test_series_keep_to_the_named_events(
    client: Client, league: dict[str, Any]
) -> None:
    p1 = league["player_ids"][0]
    only = client.get(f"/users/{p1}/series?event_id={league['second_id']}").json()
    assert {row["season_id"] for row in only} == {league["second_id"]}
    none = client.get(f"/users/{p1}/series?event_id={league['third_id']}")
    assert none.json() == []
    assert none.headers["x-total-count"] == "0"
    assert client.get(f"/users/{p1}/series").status_code == 422
    many = "&".join(f"event_id={number}" for number in range(51))
    assert client.get(f"/users/{p1}/series?{many}").status_code == 422


def test_one_career_row_is_the_list_row(client: Client, league: dict[str, Any]) -> None:
    listed = {
        row["user_id"]: row
        for row in client.get("/stats/career").json()
        if row["user_id"] is not None
    }
    # P3 holds no stored row and has played, P4 has neither a row nor a result
    assert league["player_ids"][2] in listed
    assert league["player_ids"][3] not in listed
    for user_id in league["player_ids"]:
        resp = client.get(f"/stats/career/{user_id}")
        if user_id in listed:
            assert resp.status_code == 200
            assert resp.json() == listed[user_id]
        else:
            assert resp.status_code == 404


# The fields of /users/{id} a player page reads, which the summary answers
SUMMARY_FIELDS = (
    "id",
    "name",
    "battleTag",
    "country",
    "race_mmrs",
    "main_race",
)


def profile_fields(client: Client, user_id: int) -> dict[str, Any]:
    """The summary fields as /users/{id} answers them, tag_names as the text of
    its tags."""
    user = client.get(f"/users/{user_id}").json()
    fields = {field: user[field] for field in SUMMARY_FIELDS}
    return fields | {"tag_names": [tag["tag"] for tag in user["tags"]]}


@pytest.mark.parametrize("season", [None, "24", ""])
def test_the_summary_answers_what_the_profile_answers(
    client: Client,
    ladder: list[int],  # noqa: F811  # fixture
    season: str | None,
) -> None:
    """Window, stale and unrated races, a race with no name, a second tag, no
    tag, a season setting that leaves the newest rows outside the window, and a
    blank setting, which reads the newest stored season."""
    alt, no_tag = ladder[1], ladder[3]
    with Session.begin() as session:
        if season is not None:
            session.add(Settings(key=W3C_SEASON_KEY, value=season))
        session.add_all(
            [
                W3CStats(user_id=no_tag, race=None, wc3_season=25, mmr=1400, games=12),
                W3CStats(user_id=no_tag, race=None, wc3_season=22, mmr=1300, games=3),
                W3CStats(user_id=no_tag, race=Race.OC, wc3_season=21, games=2),
                W3CStats(user_id=alt, race=Race.HU, wc3_season=25, games=3),
            ]
        )
        session.execute(
            delete(UserBattleTag).where(col(UserBattleTag.user_id) == no_tag)
        )
        old = session.scalars(
            select(UserBattleTag).where(col(UserBattleTag.user_id) == alt)
        ).one()
        old.is_active = False
        old_tag = old.tag
    with Session.begin() as session:
        (tag,) = active("Alt#2222")
        tag.user_id = alt
        session.add(tag)
    for user_id in ladder:
        resp = client.get(f"/users/{user_id}/summary")
        assert resp.status_code == 200
        assert resp.json() == profile_fields(client, user_id)
    second = client.get(f"/users/{alt}/summary").json()
    assert second["battleTag"] == "Alt#2222"
    assert second["tag_names"] == ["Alt#2222", old_tag]
    bare = client.get(f"/users/{no_tag}/summary").json()
    assert (bare["battleTag"], bare["tag_names"]) == (None, [])
    # the season 25 row is outside a window that ends at 24
    newest = (None, 22, True) if season == "24" else (None, 25, False)
    assert [
        (row["race"], row["wc3_season"], row["stale"]) for row in bare["race_mmrs"]
    ] == [
        newest,
        ("OC", 21, True),
    ]


def test_a_newer_unrated_row_gives_way_to_an_older_rated_one(
    client: Client,
    ladder: list[int],  # noqa: F811  # fixture
) -> None:
    """In a window that ends at 25, the race reads its newest rated row with the
    games of every window row; the HU row of season 20 is outside it."""
    user_id = ladder[2]
    with Session.begin() as session:
        session.add_all(
            [
                W3CStats(user_id=user_id, race=Race.HU, wc3_season=25, games=3),
                W3CStats(
                    user_id=user_id, race=Race.HU, wc3_season=24, mmr=1750, games=15
                ),
            ]
        )
    resp = client.get(f"/users/{user_id}/summary")
    assert resp.json() == profile_fields(client, user_id)
    assert [
        (row["race"], row["mmr"], row["wc3_season"], row["games"], row["stale"])
        for row in resp.json()["race_mmrs"]
    ] == [("HU", 1750, 24, 18, False)]
    assert resp.json()["main_race"] == "HU"


def test_a_player_with_no_rows_has_a_bare_summary(client: Client) -> None:
    with Session.begin() as session:
        person = User(name="Bare", discordTag=None, discordId=None, race=Race.HU)
        session.add(person)
        session.flush()
        user_id = ident(person)
    resp = client.get(f"/users/{user_id}/summary")
    assert resp.status_code == 200
    assert resp.json() == {
        "id": user_id,
        "name": "Bare",
        "battleTag": None,
        "country": None,
        "tag_names": [],
        "race_mmrs": [],
        "main_race": None,
    }
    assert resp.json() == profile_fields(client, user_id)


def test_an_unknown_player_has_no_summary(client: Client) -> None:
    """The same 404 as /users/{key}."""
    resp = client.get("/users/999999/summary")
    assert resp.status_code == 404
    assert resp.json() == client.get("/users/999999").json()
    assert resp.json() == {"error": "User not found: 999999"}
