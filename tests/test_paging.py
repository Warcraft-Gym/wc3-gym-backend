"""The list routes answer at most 500 rows, and the cap is SQL.

Every route in PAGED_ROUTES takes limit and offset. A limit outside
1..500 answers 422, and the default limit is 500. The cap goes into the
statement as LIMIT, so a large table never becomes a large Python list.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from httpx2 import Client
from sqlalchemy import event, select

from app.core.db import Session

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
            select(KothEvent.id).order_by(KothEvent.id)
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

    service = TeamService(user_app_service=None)
    with capture_sql() as statements:
        teams = service.getAll(limit=1)
    assert len(teams) == 1
    assert any("LIMIT" in statement for statement in statements)
