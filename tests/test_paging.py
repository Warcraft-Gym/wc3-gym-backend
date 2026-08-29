"""The list routes answer at most 500 rows, and the cap is SQL.

Every route in PAGED_ROUTES takes limit and offset. A limit outside
1..500 answers 422, and the default limit is 500. The cap goes into the
statement as LIMIT, so a large table never becomes a large Python list.

Three routes also take sort and order. DEFAULT_ORDER holds the ORDER BY
every route writes without a sort parameter, so a change to one of them
fails the guard test.
"""

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, get_args

import pytest
from httpx2 import Client
from sqlalchemy import event, select
from sqlmodel import col

from app.core.db import Session
from app.models.base import ident

# The path templates take the ids of the seeded league
PAGED_ROUTES = [
    ("GET", "/seasons"),
    ("POST", "/seasons/search?query=id > 0"),
    ("GET", "/seasons/{season_id}/signups"),
    ("POST", "/matches/search?query=id > 0"),
    ("POST", "/series/search?query=id > 0"),
    ("GET", "/series/season/{season_id}"),
    ("POST", "/series/season/{season_id}/search?query=id > 0"),
    ("POST", "/series/season/{season_id}/playday/1/search?query=id > 0"),
    ("GET", "/teams"),
    ("GET", "/teams/basic"),
    ("POST", "/teams/search?query=id > 0"),
    ("GET", "/teams/season/{season_id}"),
    ("GET", "/teams/season/{season_id}/basic"),
    ("GET", "/users"),
    ("POST", "/users/search?query=id > 0"),
    ("GET", "/maps"),
    ("POST", "/maps/search?query=id > 0"),
    ("GET", "/fantasy/teams"),
    ("POST", "/fantasy/teams/search?query=id > 0"),
    ("GET", "/fantasy/bets"),
    ("POST", "/fantasy/bets/search?query=id > 0"),
    ("GET", "/draft-series/match/{match_id}"),
    ("GET", "/koth/events/{event_id}/signups"),
    ("GET", "/koth/events/{event_id}/matches"),
    ("GET", "/player-series?token=none"),
]


def build(path: str, seeded: dict[str, Any], **params: int) -> str:
    """The path with the seeded ids and the paging parameters in place."""
    path = path.format(
        season_id=seeded["season_id"],
        match_id=seeded["match_id"],
        event_id=seeded["koth_event_id"],
    )
    separator = "&" if "?" in path else "?"
    query = "&".join(f"{name}={value}" for name, value in params.items())
    return f"{path}{separator}{query}"


@contextmanager
def capture_sql() -> Iterator[list[str]]:
    """Report the statements the engine sent inside the block."""
    with Session() as session:
        engine = session.get_bind()
    statements: list[str] = []

    def on_execute(conn: object, cursor: object, statement: str, *args: object) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", on_execute)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", on_execute)


@pytest.fixture
def league(seeded: dict[str, Any]) -> dict[str, Any]:
    """The seeded league plus the id of its KOTH event."""
    from app.models.koth_event import KothEvent

    with Session() as session:
        seeded["koth_event_id"] = session.scalar(
            select(col(KothEvent.id)).order_by(col(KothEvent.id))
        )
    return seeded


@pytest.mark.parametrize(("method", "path"), PAGED_ROUTES)
def test_a_limit_outside_the_range_is_rejected(
    client: Client, league: dict[str, Any], method: str, path: str
) -> None:
    """limit 0 and limit 501 answer 422; the cap is 500."""
    for params in ({"limit": 0}, {"limit": 501}, {"offset": -1}):
        url = build(path, league, **params)
        resp = client.request(method, url)
        assert resp.status_code == 422, f"{method} {url}"


@pytest.mark.parametrize(("method", "path"), PAGED_ROUTES)
def test_the_cap_itself_is_accepted(
    client: Client, league: dict[str, Any], method: str, path: str
) -> None:
    """limit 1 and limit 500 pass validation on every paged route."""
    for params in ({"limit": 1}, {"limit": 500, "offset": 0}):
        url = build(path, league, **params)
        resp = client.request(method, url)
        assert resp.status_code != 422, f"{method} {url}"


def test_the_default_limit_cuts_a_long_list(client: Client) -> None:
    """600 maps, and the route answers the first 500 of them."""
    from app.models.map import Map

    with Session() as session:
        for number in range(600):
            session.add(Map(name=f"Map {number:03d}", shortname=f"M{number:03d}"))
        session.commit()

    resp = client.get("/maps")
    assert resp.status_code == 200
    assert len(resp.json()) == 500


def test_offset_walks_the_seeded_users(client: Client, league: dict[str, Any]) -> None:
    """Two pages of two users hold the four seeded users, each once."""
    query = "query=id > 0"
    everything = client.post(f"/users/search?{query}")
    ids = sorted(user["id"] for user in everything.json())
    assert len(ids) == 4

    paged = []
    for offset in (0, 2):
        resp = client.post(f"/users/search?{query}&limit=2&offset={offset}")
        assert resp.status_code == 200
        page = [user["id"] for user in resp.json()]
        assert len(page) == 2
        paged += page
    assert paged == ids


def test_offset_past_the_end_answers_an_empty_list(
    client: Client, league: dict[str, Any]
) -> None:
    resp = client.get("/teams?limit=10&offset=10")
    assert resp.status_code == 200
    assert resp.json() == []


def test_a_page_carries_whole_rows(client: Client, league: dict[str, Any]) -> None:
    """One team per page, and that team still carries its two players.

    The route joins the roster, so the LIMIT belongs to an inner select
    over the teams alone. SQLAlchemy writes that subquery itself.
    """
    season_id = league["season_id"]
    pages = []
    for offset in (0, 1):
        resp = client.get(f"/teams/season/{season_id}?limit=1&offset={offset}")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        pages.append(resp.json()[0])

    assert [team["id"] for team in pages] == [league["team_a_id"], league["team_b_id"]]
    for team in pages:
        assert len(team["player_by_season"][str(season_id)]) == 2


def test_the_limit_reaches_the_statement(league: dict[str, Any]) -> None:
    """The service asks the database for one row, it does not slice a list."""
    from app.services.teams import TeamService
    from app.services.users import UserService

    service = TeamService(UserService())
    with capture_sql() as statements:
        teams = service.get_all(limit=1)
    assert len(teams) == 1
    assert any("LIMIT" in statement for statement in statements)


# The ORDER BY every route writes when no sort parameter is sent
DEFAULT_ORDER = {
    "GET /seasons": ["seasons.id"],
    "POST /seasons/search?query=id > 0": ["seasons.id"],
    "GET /seasons/{season_id}/signups": [
        "user_season_signup.user_id",
        "anon_1.user_id",
    ],
    "POST /matches/search?query=id > 0": ["matches.id"],
    "POST /series/search?query=id > 0": ["series.id"],
    "GET /series/season/{season_id}": ["series.id"],
    "POST /series/season/{season_id}/search?query=id > 0": ["series.id"],
    "POST /series/season/{season_id}/playday/1/search?query=id > 0": ["series.id"],
    "GET /teams": ["teams.id"],
    "GET /teams/basic": ["teams.id"],
    "POST /teams/search?query=id > 0": ["teams.id"],
    # The last fragment orders the matchup history of the season record
    "GET /teams/season/{season_id}": [
        "teams.id",
        "anon_1.id",
        "anon_1.playday, anon_1.series_id",
    ],
    "GET /teams/season/{season_id}/basic": ["teams.id", "anon_1.id"],
    "GET /users": ["users.id", "anon_1.id"],
    "POST /users/search?query=id > 0": ["users.id", "anon_1.id"],
    "GET /maps": ["maps.id"],
    "POST /maps/search?query=id > 0": ["maps.id"],
    "GET /fantasy/teams": ["fantasy_teams.id", "anon_1.id"],
    "POST /fantasy/teams/search?query=id > 0": ["fantasy_teams.id", "anon_1.id"],
    "GET /fantasy/bets": ["fantasy_bets.id"],
    "POST /fantasy/bets/search?query=id > 0": ["fantasy_bets.id"],
    "GET /draft-series/match/{match_id}": ["draft_series.id"],
    "GET /koth/events/{event_id}/signups": [
        "koth_signups.bracket, koth_signups.mmr DESC, koth_signups.id"
    ],
    "GET /koth/events/{event_id}/matches": [
        "koth_matches.bracket, koth_matches.id",
        "anon_1.bracket, anon_1.id",
    ],
    "GET /player-series?token=none": ["series.id"],
}

ORDER_BY = re.compile(r"ORDER BY (.+?)(?:\s+LIMIT|\s*$)", re.DOTALL)


@pytest.fixture
def dashboard_token() -> Iterator[Callable[..., str]]:
    """A factory for dashboard tokens of the seeded player P1."""
    from app.api.routes.public import _token_store

    issued: list[str] = []

    def issue(season_id: int | None = None) -> str:
        token = f"sort-token-{len(issued)}"
        _token_store[token] = {
            "discord_id": "1",
            "discord_tag": "p1",
            "season_id": str(season_id) if season_id else None,
            "access_type": "dashboard",
            "expires_at": datetime.now(UTC) + timedelta(minutes=5),
        }
        issued.append(token)
        return token

    yield issue
    for token in issued:
        _token_store.pop(token, None)


def order_fragments(statements: list[str]) -> list[str]:
    """The ORDER BY of every statement, on one line each."""
    return [
        " ".join(found.split())
        for statement in statements
        for found in ORDER_BY.findall(statement)
    ]


@pytest.mark.parametrize(("method", "path"), PAGED_ROUTES)
def test_the_default_order_holds_without_a_sort(
    client: Client,
    league: dict[str, Any],
    dashboard_token: Callable[..., str],
    method: str,
    path: str,
) -> None:
    """No sort parameter, and every route orders the way it does today."""
    url = build(path, league).rstrip("?&")
    url = url.replace("token=none", f"token={dashboard_token()}")
    with capture_sql() as statements:
        resp = client.request(method, url)
    assert resp.status_code == 200, url
    assert order_fragments(statements) == DEFAULT_ORDER[f"{method} {path}"]


def test_the_sort_names_are_declared_once() -> None:
    """Each route's Literal holds exactly the names of its sort map."""
    from app.models.series import SERIES_SORTS, SeriesSort
    from app.services.derived import CAREER_SORTS, CareerSort
    from app.services.fantasy_bets import BET_SORTS, BetSort

    assert set(get_args(BetSort)) == set(BET_SORTS)
    assert set(get_args(SeriesSort)) == set(SERIES_SORTS)
    assert set(get_args(CareerSort)) == set(CAREER_SORTS)


SORTED_ROUTES = [
    ("POST", "/fantasy/bets/search?query=id > 0", "bet_points"),
    ("GET", "/player-series?token=none", "date_time"),
    ("GET", "/stats/career", "rating"),
]


@pytest.mark.parametrize(("method", "path", "name"), SORTED_ROUTES)
def test_an_unknown_sort_or_order_is_rejected(
    client: Client,
    league: dict[str, Any],
    dashboard_token: Callable[..., str],
    method: str,
    path: str,
    name: str,
) -> None:
    """A name outside the map and a direction outside asc/desc answer 422."""
    url = path.replace("token=none", f"token={dashboard_token()}")
    separator = "&" if "?" in url else "?"
    for query in ("sort=not_a_column", f"sort={name}&order=sideways"):
        resp = client.request(method, f"{url}{separator}{query}")
        assert resp.status_code == 422, f"{method} {url}{separator}{query}"


def seed_more_bets(league: dict[str, Any]) -> None:
    """Three more bets, so the four bet sort names have rows to order.

    The captains P2, P4 and P3 join the seeded bet of P1.
    """
    from app.models.fantasy_bet import FantasyBet

    players = league["player_ids"]
    played, open_series = league["series_played_id"], league["series_open_id"]
    with Session() as session:
        session.add_all(
            [
                FantasyBet(
                    season_id=league["season_id"],
                    series_id=open_series,
                    user_id=players[1],
                    winner_id=players[1],
                    bet_points=25,
                ),
                FantasyBet(
                    season_id=league["season_id"],
                    series_id=played,
                    user_id=players[3],
                    winner_id=players[0],
                    bet_points=5,
                ),
                FantasyBet(
                    season_id=league["season_id"],
                    series_id=open_series,
                    user_id=players[2],
                    winner_id=players[2],
                    bet_points=20,
                ),
            ]
        )
        session.commit()


BET_KEYS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "id": lambda bet: bet["id"],
    "bet_points": lambda bet: bet["bet_points"],
    "captain": lambda bet: bet["user"]["name"],
    "series_id": lambda bet: bet["series_id"],
}


@pytest.mark.parametrize("order", ["asc", "desc"])
@pytest.mark.parametrize("name", list(BET_KEYS))
def test_bets_sort_by_every_name(
    client: Client, league: dict[str, Any], name: str, order: str
) -> None:
    """The sorted list runs one way, and pages of two walk it in that order."""
    seed_more_bets(league)
    url = f"/fantasy/bets/search?query=id > 0&sort={name}&order={order}"

    resp = client.post(f"{url}&limit=500")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 4
    keys = [BET_KEYS[name](bet) for bet in rows]
    assert keys == sorted(keys, reverse=order == "desc")

    walked = []
    for offset in (0, 2):
        page = client.post(f"{url}&limit=2&offset={offset}")
        assert page.status_code == 200
        walked += [bet["id"] for bet in page.json()]
    assert walked == [bet["id"] for bet in rows]


def test_the_captain_sort_does_not_multiply_the_page(
    client: Client, league: dict[str, Any]
) -> None:
    """The join for the captain name is to one user, so the page keeps its size."""
    seed_more_bets(league)
    query = "query=id > 0"
    plain = client.post(f"/fantasy/bets/search?{query}&limit=3")
    sorted_page = client.post(f"/fantasy/bets/search?{query}&limit=3&sort=captain")
    assert plain.status_code == sorted_page.status_code == 200
    assert len(sorted_page.json()) == len(plain.json()) == 3
    assert plain.headers["X-Total-Count"] == sorted_page.headers["X-Total-Count"] == "4"


def seed_more_series(league: dict[str, Any]) -> None:
    """Three more series of the seeded player P1, over three playdays.

    One of them carries no date, which is the null the order has to place.
    """
    from app.models.match import Match
    from app.models.series import Series

    players = league["player_ids"]
    with Session() as session:
        later = [
            Match(
                team1_id=league["team_a_id"],
                team2_id=league["team_b_id"],
                season_id=league["season_id"],
                playday=playday,
            )
            for playday in (2, 3)
        ]
        session.add_all(later)
        session.flush()
        session.add_all(
            [
                Series(
                    match_id=league["match_id"],
                    date_time=datetime(2026, 1, 8, 19, 0),
                    player1_id=players[0],
                    player2_id=players[3],
                    host_player_id=players[0],
                ),
                Series(
                    match_id=ident(later[0]),
                    date_time=datetime(2026, 1, 14, 19, 0),
                    player1_id=players[0],
                    player2_id=players[2],
                    host_player_id=players[0],
                ),
                Series(
                    match_id=ident(later[1]),
                    date_time=None,
                    player1_id=players[0],
                    player2_id=players[3],
                    host_player_id=players[0],
                ),
            ]
        )
        session.commit()


SERIES_KEYS: dict[str, Callable[[dict[str, Any]], Any]] = {
    # A series with no date sorts first ascending, so the empty string stands in
    "date_time": lambda series: series["date_time"] or "",
    "week": lambda series: series["match"]["playday"],
    "id": lambda series: series["id"],
}


@pytest.mark.parametrize("in_season", [False, True])
@pytest.mark.parametrize("order", ["asc", "desc"])
@pytest.mark.parametrize("name", list(SERIES_KEYS))
def test_player_series_sorts_by_every_name(
    client: Client,
    league: dict[str, Any],
    dashboard_token: Callable[..., str],
    name: str,
    order: str,
    in_season: bool,
) -> None:
    """Both branches of the route sort, and pages of two walk the same order."""
    seed_more_series(league)
    token = dashboard_token(league["season_id"] if in_season else None)
    url = f"/player-series?token={token}&sort={name}&order={order}"

    resp = client.get(f"{url}&limit=500")
    assert resp.status_code == 200
    rows = resp.json()["series"]
    assert len(rows) == 4
    keys = [SERIES_KEYS[name](series) for series in rows]
    assert keys == sorted(keys, reverse=order == "desc")

    walked = []
    for offset in (0, 2):
        page = client.get(f"{url}&limit=2&offset={offset}")
        assert page.status_code == 200
        walked += [series["id"] for series in page.json()["series"]]
    assert walked == [series["id"] for series in rows]


@pytest.mark.parametrize("in_season", [False, True])
def test_a_series_without_a_date_sorts_first_then_last(
    client: Client,
    league: dict[str, Any],
    dashboard_token: Callable[..., str],
    in_season: bool,
) -> None:
    """A null date leads the ascending page and closes the descending one."""
    seed_more_series(league)
    token = dashboard_token(league["season_id"] if in_season else None)
    dates = {}
    for order in ("asc", "desc"):
        resp = client.get(f"/player-series?token={token}&sort=date_time&order={order}")
        assert resp.status_code == 200
        dates[order] = [series["date_time"] for series in resp.json()["series"]]
    assert dates["asc"][0] is None
    assert dates["desc"][-1] is None
    assert dates["asc"] == list(reversed(dates["desc"]))


def seed_more_career_rows(league: dict[str, Any]) -> None:
    """Three unmapped career rows. Two of them tie on every total."""
    from app.models.player_career_stats import PlayerCareerStats

    with Session() as session:
        session.add_all(
            [
                PlayerCareerStats(
                    player_name=name,
                    historical_rating=rating,
                    historical_series_won=won,
                    historical_series_lost=lost,
                    historical_games_won=won * 2,
                    historical_games_lost=lost * 2,
                    historical_seasons_played=seasons,
                )
                for name, rating, won, lost, seasons in (
                    ("Tie A", 500, 7, 1, 3),
                    ("Tie B", 500, 7, 1, 3),
                    ("zulu", 200, 2, 6, 1),
                )
            ]
        )
        session.commit()


CAREER_KEYS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "name": lambda row: (
        (row["user"]["name"] if row["user"] else row["player_name"]) or ""
    ).casefold(),
    "mapped": lambda row: row["user_id"] is not None,
    "rating": lambda row: row["rating"],
    "series_won": lambda row: row["series_won"],
    "series_lost": lambda row: row["series_lost"],
    "series_winrate": lambda row: row["series_winrate"],
    "games_won": lambda row: row["games_won"],
    "games_lost": lambda row: row["games_lost"],
    "games_winrate": lambda row: row["games_winrate"],
    "seasons_played": lambda row: row["seasons_played"],
}


@pytest.mark.parametrize("order", ["asc", "desc"])
@pytest.mark.parametrize("name", list(CAREER_KEYS))
def test_career_sorts_by_every_name(
    client: Client, league: dict[str, Any], name: str, order: str
) -> None:
    """The sorted list runs one way, and pages of two walk it in that order."""
    seed_more_career_rows(league)
    url = f"/stats/career?sort={name}&order={order}"

    resp = client.get(url)
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 6
    keys = [CAREER_KEYS[name](row) for row in rows]
    assert keys == sorted(keys, reverse=order == "desc")

    walked = []
    for offset in (0, 2, 4):
        page = client.get(f"{url}&limit=2&offset={offset}")
        assert page.status_code == 200
        walked += [row["id"] for row in page.json()]
    assert walked == [row["id"] for row in rows]


@pytest.mark.parametrize("order", ["asc", "desc"])
def test_a_career_rating_tie_keeps_the_id_order(
    client: Client, league: dict[str, Any], order: str
) -> None:
    """Tie A and Tie B share a rating, and the smaller id leads both ways."""
    seed_more_career_rows(league)
    resp = client.get(f"/stats/career?sort=rating&order={order}")
    assert resp.status_code == 200
    tied = [row for row in resp.json() if row["player_name"].startswith("Tie ")]
    assert len(tied) == 2
    assert tied[0]["rating"] == tied[1]["rating"]
    assert tied[0]["id"] < tied[1]["id"]


@pytest.mark.parametrize("order", ["asc", "desc"])
def test_a_career_row_without_an_id_sorts_last_of_its_tie(
    client: Client, league: dict[str, Any], order: str
) -> None:
    """Every mapped row ties on mapped, and the row with no id closes them."""
    seed_more_career_rows(league)
    resp = client.get(f"/stats/career?sort=mapped&order={order}")
    assert resp.status_code == 200
    mapped = [row for row in resp.json() if row["user_id"] is not None]
    assert len(mapped) == 3
    assert [row["id"] for row in mapped[:2]] == sorted(row["id"] for row in mapped[:2])
    assert mapped[-1]["id"] is None


def test_career_search_and_sort_count_the_kept_rows(
    client: Client, league: dict[str, Any]
) -> None:
    """search runs before the sort, so the header counts the kept rows."""
    seed_more_career_rows(league)
    resp = client.get("/stats/career?search=tie&sort=name&order=desc")
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "2"
    assert [row["player_name"] for row in resp.json()] == ["Tie B", "Tie A"]
