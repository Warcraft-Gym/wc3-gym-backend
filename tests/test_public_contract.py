"""The JSON the public site reads, pinned route by route.

Five WordPress shortcodes call eight backend routes on every page view.
A dropped or renamed field breaks the rendered page with no error from
the backend, so these tests assert the fields the PHP reads and the
shapes it indexes into. They assert presence and shape, not values,
except where a value proves the season filter.

The shortcodes and the routes they call:
  gnl-player-stats        GET  /stats/career
  gnl-detailed-standings  GET  /config/settings, GET /teams/season/{id},
                          GET /seasons/{id}, POST /matches/search
  gnl-teams-players       GET  /config/settings, GET /teams/season/{id},
                          GET /teams/{id}/image
  gnl-week-series         GET  /config/settings, POST /matches/search,
                          POST /series/season/{id}/playday/{n}/search
  gnl-fantasy-teams       GET  /config/settings, POST /fantasy/teams/search
  gnl-fantasy-leaderboard GET  /config/settings, POST /fantasy/teams/search
"""

from datetime import date
from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import Client

from app.models.base import ident

# The image route serves the stored bytes back untouched, so any bytes work.
TEAM_ICON = b"\x89PNG\r\n\x1a\npublic-contract-test"

# The w3champions season the shortcodes select w3c_stats rows by.
WC3_SEASON = 20

# The scheduled time tests/seed.py inserts; the PHP splits it on 'T', '-' and ':'.
SERIES_DATE_TIME = "2026-01-07T19:00:00Z"


@pytest.fixture
def public_seed(app: FastAPI) -> dict[str, Any]:
    """The seeded league plus everything the shortcodes read.

    Team Alpha joins a second season, so the season filter on
    GET /teams/season/{id} is proved rather than assumed.
    """
    from app.core.db import Session
    from app.models.enums import Race
    from app.models.fantasy_team import FantasyTeam
    from app.models.relationships import DBFantasyTeamPlayer, DBTeamSeasonCoach
    from app.models.season import Season
    from app.models.settings import Settings
    from app.models.team import Team
    from app.models.team_season import DBTeamSeason
    from app.models.user import User
    from app.models.user_team_season import DBUserTeamSeason
    from app.models.w3c_stats import W3CStats
    from tests.seed import seed_league

    with Session() as session:
        ids = seed_league(session)
        session.flush()

        season_2 = Season(
            name="Season 2",
            number_weeks=6,
            series_per_week=2,
            start_date=date(2026, 3, 2),
            end_date=date(2026, 4, 24),
        )
        coach = User(
            name="C1",
            battleTag="C1#9999",
            discordTag="c1",
            discordId="9",
            race=Race.RANDOM,
            mmr=1700,
            country="PL",
        )
        session.add_all([season_2, coach])
        session.flush()

        # Alpha plays two seasons; Beta plays one. The score columns stay
        # empty, because the standings are summed from the series.
        session.add(DBTeamSeason(team_id=ids["team_a_id"], season_id=ident(season_2)))
        session.add(
            DBUserTeamSeason(
                user_id=ids["player_ids"][3],
                team_id=ids["team_a_id"],
                season_id=ident(season_2),
            )
        )

        for team_id in (ids["team_a_id"], ids["team_b_id"]):
            session.add(
                DBTeamSeasonCoach(
                    team_id=team_id, season_id=ids["season_id"], user_id=ident(coach)
                )
            )

        session.get(Team, ids["team_a_id"]).icon = TEAM_ICON

        for user_id, mmr, race in zip(
            ids["player_ids"],
            (1550, 1450, 1650, 1350),
            (Race.HU, Race.OC, Race.NE, Race.UD),
            strict=True,
        ):
            session.add(
                W3CStats(
                    user_id=user_id,
                    wc3_season=WC3_SEASON,
                    race=race,
                    mmr=mmr,
                    wins=10,
                    losses=4,
                    games=14,
                    winrate=0.71,
                    league=2,
                )
            )

        session.add_all(
            [
                Settings(
                    key="current_gnl_season",
                    value=str(ids["season_id"]),
                    description="Season the shortcodes render",
                ),
                Settings(key="current_wc3_season", value=str(WC3_SEASON)),
            ]
        )

        session.add_all(
            [
                DBFantasyTeamPlayer(
                    fantasy_team_id=ids["fantasy_team_id"], user_id=user_id
                )
                for user_id in ids["player_ids"][:2]
            ]
        )

        # A second team drafts nobody, so the empty draft list is proved.
        empty_team = FantasyTeam(
            name="The Undrafted",
            season_id=ids["season_id"],
            captain_id=ids["player_ids"][2],
            drafted_team_id=ids["team_b_id"],
            drafted_race=Race.NE,
        )
        session.add(empty_team)
        session.flush()

        ids["season_2_id"] = season_2.id
        ids["coach_id"] = coach.id
        ids["empty_fantasy_team_id"] = empty_team.id
        session.commit()

    return ids


def get_json(client: Client, path: str) -> Any:  # noqa: ANN401  # a JSON body
    resp = client.get(path)
    assert resp.status_code == 200
    return resp.json()


def post_json(client: Client, path: str, query: str = "") -> Any:  # noqa: ANN401
    resp = client.post(path, params={"query": query} if query else None)
    assert resp.status_code == 200
    return resp.json()


# gnl-player-stats


def test_career_stats_carries_the_player_table_fields(
    client: Client, public_seed: dict[str, Any]
) -> None:
    stats = get_json(client, "/stats/career")
    assert stats
    for stat in stats:
        assert "player_name" in stat
        assert "rating" in stat
        assert "series_won" in stat
        assert "series_lost" in stat
        assert "series_winrate" in stat
    linked = next(s for s in stats if s["user"] is not None)
    # The name comes from user.name and falls back to player_name.
    assert "name" in linked["user"]
    assert linked["user"]["name"]
    assert linked["player_name"]
    assert linked["rating"] is not None
    assert linked["series_winrate"] is not None


# gnl-detailed-standings, gnl-teams-players, gnl-week-series, both fantasy pages


def test_config_settings_carries_the_season_selector(
    client: Client, public_seed: dict[str, Any]
) -> None:
    body = get_json(client, "/config/settings")
    assert isinstance(body["settings"], list)
    by_key = {s["key"]: s for s in body["settings"]}
    for setting in body["settings"]:
        assert "key" in setting
        assert "value" in setting
    # Every shortcode picks its season out of this key.
    assert by_key["current_gnl_season"]["value"] == str(public_seed["season_id"])
    assert by_key["current_wc3_season"]["value"] == str(WC3_SEASON)


# gnl-detailed-standings, gnl-teams-players


def test_teams_season_carries_the_standings_and_roster_fields(
    client: Client, public_seed: dict[str, Any]
) -> None:
    season_id = public_seed["season_id"]
    teams = get_json(client, f"/teams/season/{season_id}")
    assert len(teams) == 2
    # The standings are summed from the one played series, a 2-1 for Alpha.
    # Season 1 pays 4 weeks * 2 series * 3 points, so 24 less what both took.
    expected = {"Alpha": (2, 1, 21), "Beta": (1, 2, 21)}
    for team in teams:
        assert "id" in team
        assert "name" in team
        assert "long_name" in team
        # The standings table reads the score columns off seasons_info[0].
        assert isinstance(team["seasons_info"], list)
        info = team["seasons_info"][0]
        assert "final_score" in info
        assert "points_available" in info
        assert "points_against" in info
        # No shortcode reads a season off the entry; the route sends season_id.
        assert set(info) == {
            "season_id",
            "final_score",
            "points_available",
            "points_against",
        }
        # Season 2 pays 36 and holds no series, so equality proves the season row.
        assert (
            info["final_score"],
            info["points_against"],
            info["points_available"],
        ) == expected[team["name"]]
        # Both maps are keyed by season id, not by position.
        assert isinstance(team["player_by_season"], dict)
        assert isinstance(team["coaches_by_season"], dict)
        assert team["player_by_season"][str(season_id)]
        assert team["coaches_by_season"][str(season_id)]


def test_teams_season_carries_the_person_row_fields(
    client: Client, public_seed: dict[str, Any]
) -> None:
    season_id = public_seed["season_id"]
    teams = get_json(client, f"/teams/season/{season_id}")
    people = [
        person
        for team in teams
        for group in ("player_by_season", "coaches_by_season")
        for person in team[group][str(season_id)]
    ]
    assert people
    for person in people:
        assert person["name"]
        assert person["battleTag"]
        assert person["discordTag"]
        assert person["race"]
        assert person["country"]
        assert person["mmr"] is not None
        assert isinstance(person["w3c_stats"], list)
    # The roster sorts on the w3c_stats row for the configured w3c season.
    rated = next(p for p in people if p["w3c_stats"])
    stat = rated["w3c_stats"][0]
    assert stat["wc3_season"] == WC3_SEASON
    assert stat["mmr"] is not None
    assert stat["race"]


def test_teams_season_seasons_info_holds_only_the_requested_season(
    client: Client, public_seed: dict[str, Any]
) -> None:
    """HARD GATE: the standings read seasons_info[0] by index."""
    season_id = public_seed["season_id"]
    team_a_id = public_seed["team_a_id"]

    # Alpha really is in two seasons: the unfiltered route returns both.
    unfiltered = get_json(client, f"/teams/{team_a_id}")
    assert len(unfiltered["seasons_info"]) == 2

    teams = get_json(client, f"/teams/season/{season_id}")
    for team in teams:
        assert len(team["seasons_info"]) == 1, (
            f"team {team['id']} returned {len(team['seasons_info'])} seasons_info "
            "entries; the standings read index 0"
        )
        assert team["seasons_info"][0]["season_id"] == season_id
    # The roster map is filtered to the same one season.
    alpha = next(t for t in teams if t["id"] == team_a_id)
    assert list(alpha["player_by_season"]) == [str(season_id)]


def test_team_image_serves_an_image(
    client: Client, public_seed: dict[str, Any]
) -> None:
    resp = client.get(f"/teams/{public_seed['team_a_id']}/image")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")
    assert resp.content == TEAM_ICON


def test_team_image_is_cached_by_its_content(
    client: Client, public_seed: dict[str, Any]
) -> None:
    """A day of browser cache, a tag of the bytes, and 304 on a repeat."""
    path = f"/teams/{public_seed['team_a_id']}/image"
    resp = client.get(path)
    assert resp.headers["cache-control"] == "public, max-age=86400"
    etag = resp.headers["etag"]
    assert etag

    again = client.get(path, headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == etag


# gnl-detailed-standings


def test_season_carries_number_weeks_and_the_list_fields(
    client: Client, public_seed: dict[str, Any]
) -> None:
    season = get_json(client, f"/seasons/{public_seed['season_id']}")
    assert "number_weeks" in season
    assert season["number_weeks"] is not None
    # Both fields read as a list, never as null.
    assert isinstance(season["maps"], list)
    assert isinstance(season["user_signup"], list)
    assert season["user_signup"] == []


def test_matches_search_carries_the_standings_fields(
    client: Client, public_seed: dict[str, Any]
) -> None:
    matches = post_json(
        client, "/matches/search", f"season_id=={public_seed['season_id']}"
    )
    assert matches
    for match in matches:
        assert "id" in match
        assert "playday" in match
        assert "team1_id" in match
        assert "team2_id" in match
        assert "team1_score" in match
        assert "team2_score" in match
        assert match["playday"] is not None
        assert match["team1_id"] is not None
        assert match["team2_id"] is not None
    # The standings add the scores up, so pin the seeded result.
    seeded = next(m for m in matches if m["id"] == public_seed["match_id"])
    assert seeded["team1_score"] == 2
    assert seeded["team2_score"] == 1


# gnl-week-series


def test_matches_search_by_playday_carries_the_team_names(
    client: Client, public_seed: dict[str, Any]
) -> None:
    query = f"season_id=={public_seed['season_id']} and playday==1"
    matches = post_json(client, "/matches/search", query)
    assert matches
    for match in matches:
        assert match["playday"] == 1
        for side in ("team1", "team2"):
            assert match[side]["name"]
            assert "long_name" in match[side]


def test_series_by_season_and_playday_carries_the_week_table_fields(
    client: Client, public_seed: dict[str, Any]
) -> None:
    season_id = public_seed["season_id"]
    series = post_json(client, f"/series/season/{season_id}/playday/1/search")
    assert len(series) == 2
    for entry in series:
        assert "id" in entry
        assert "match_id" in entry
        assert "date_time" in entry
        assert "player1_score" in entry
        assert "player2_score" in entry
        assert entry["match_id"] is not None
        for side in ("player1", "player2"):
            assert entry[side]["name"]
    # The week table groups on a scheduled time and parses that exact format.
    scheduled = next(s for s in series if s["date_time"] is not None)
    assert scheduled["date_time"] == SERIES_DATE_TIME


# gnl-fantasy-teams, gnl-fantasy-leaderboard


def test_fantasy_teams_search_carries_the_leaderboard_fields(
    client: Client, public_seed: dict[str, Any]
) -> None:
    teams = post_json(
        client, "/fantasy/teams/search", f"season_id=={public_seed['season_id']}"
    )
    assert teams
    for team in teams:
        assert team["name"]
        assert team["captain"]["name"]
        assert team["captain"]["discordTag"]
        for column in (
            "total_points",
            "player_points",
            "bench_points",
            "team_points",
            "race_points",
            "bet_points",
        ):
            assert team[column] is not None


def test_fantasy_teams_search_carries_the_draft_fields(
    client: Client, public_seed: dict[str, Any]
) -> None:
    teams = post_json(
        client, "/fantasy/teams/search", f"season_id=={public_seed['season_id']}"
    )
    assert len(teams) == 2
    for team in teams:
        assert isinstance(team["drafted_players"], list)
        for player in team["drafted_players"]:
            assert player["name"]
            assert player["discordTag"]
        assert team["drafted_team"]["name"]
        assert team["drafted_race"]
    drafted = next(t for t in teams if t["id"] == public_seed["fantasy_team_id"])
    assert len(drafted["drafted_players"]) == 2
    # A team that drafted nobody reads as an empty list, never as null.
    empty = next(t for t in teams if t["id"] == public_seed["empty_fantasy_team_id"])
    assert empty["drafted_players"] == []


def test_teams_season_roster_users_carry_no_signup_seasons(
    client: Client, public_seed: dict[str, Any]
) -> None:
    """The season roster keeps its stats; the free collections answer empty."""
    season_id = public_seed["season_id"]
    teams = get_json(client, f"/teams/season/{season_id}")
    players = [
        player
        for team in teams
        for player in team["player_by_season"].get(str(season_id), [])
    ]
    assert players
    for player in players:
        # The site person row reads these
        assert "w3c_stats" in player
        assert "name" in player
        # No consumer reads these on this route
        assert player["signup_seasons"] == []
    for team in teams:
        for coaches in team["coaches_by_season"].values():
            for coach in coaches:
                assert coach["gnl_stats"] == []
                assert coach["signup_seasons"] == []
