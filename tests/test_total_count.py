"""The three admin list routes report the total row count in a header.

GET /users and GET /stats/career stay unpaged by default, because the
admin views still read the full list. Both take limit and offset, and
both answer X-Total-Count with the count of all rows, not with the
length of the page. GET /player-series pages already; it now answers
X-Total-Count with the number of series of that one player.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from httpx2 import Client


def add_series_for_player(
    match_id: int, player_id: int, opponent_id: int, count: int
) -> None:
    """Put count more series of one player on one match."""
    from app.core.db import Session
    from app.models.series import Series

    with Session() as session:
        for _ in range(count):
            session.add(
                Series(
                    match_id=match_id,
                    player1_id=player_id,
                    player2_id=opponent_id,
                    host_player_id=player_id,
                )
            )
        session.commit()


@pytest.fixture
def dashboard_token() -> Iterator[Callable[..., str]]:
    """A factory for dashboard tokens of the seeded player P1."""
    from app.api.routes.public import _token_store

    issued: list[str] = []

    def issue(season_id: int | None = None) -> str:
        token = f"test-token-{len(issued)}"
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


def test_users_report_the_total_without_paging(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The unpaged list holds the four seeded users and counts them."""
    resp = client.get("/users")
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "4"
    assert len(resp.json()) == 4


def test_users_report_the_same_total_on_every_page(
    client: Client, seeded: dict[str, Any]
) -> None:
    """Two pages of two users carry the four ids, and the total stays 4."""
    everything = client.get("/users")
    ids = sorted(user["id"] for user in everything.json())

    paged = []
    for offset in (0, 2):
        resp = client.get(f"/users?limit=2&offset={offset}")
        assert resp.status_code == 200
        assert resp.headers["X-Total-Count"] == "4"
        page = resp.json()
        assert len(page) == 2
        paged += [user["id"] for user in page]
    assert paged == ids


def test_users_reject_a_bad_page(client: Client, seeded: dict[str, Any]) -> None:
    """limit 0, limit 501 and offset -1 answer 422."""
    assert client.get("/users?limit=0").status_code == 422
    assert client.get("/users?limit=501").status_code == 422
    assert client.get("/users?offset=-1").status_code == 422


def test_career_stats_report_the_total_without_paging(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The unpaged list holds the two seeded rows and the player who holds
    none, and counts all three."""
    resp = client.get("/stats/career")
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "3"
    assert len(resp.json()) == 3


def test_career_stats_report_the_same_total_on_every_page(
    client: Client, seeded: dict[str, Any]
) -> None:
    """Three pages of one row carry the three players, and the total stays 3."""
    everything = client.get("/stats/career")
    names = [stat["player_name"] for stat in everything.json()]

    paged = []
    for offset in (0, 1, 2):
        resp = client.get(f"/stats/career?limit=1&offset={offset}")
        assert resp.status_code == 200
        assert resp.headers["X-Total-Count"] == "3"
        page = resp.json()
        assert len(page) == 1
        paged += [stat["player_name"] for stat in page]
    assert paged == names


def test_career_stats_reject_a_bad_page(client: Client, seeded: dict[str, Any]) -> None:
    """limit 0, limit 501 and offset -1 answer 422."""
    assert client.get("/stats/career?limit=0").status_code == 422
    assert client.get("/stats/career?limit=501").status_code == 422
    assert client.get("/stats/career?offset=-1").status_code == 422


def test_player_series_report_the_total_of_that_player(
    client: Client, seeded: dict[str, Any], dashboard_token: Callable[..., str]
) -> None:
    """P1 has five series, and one page of two still reports five."""
    add_series_for_player(
        seeded["match_id"], seeded["player_ids"][0], seeded["player_ids"][2], 4
    )
    token = dashboard_token()

    everything = client.get(f"/player-series?token={token}")
    assert everything.status_code == 200
    assert everything.headers["X-Total-Count"] == "5"
    assert len(everything.json()["series"]) == 5

    page = client.get(f"/player-series?token={token}&limit=2")
    assert page.status_code == 200
    assert page.headers["X-Total-Count"] == "5"
    assert len(page.json()["series"]) == 2


def test_player_series_count_holds_to_the_season_of_the_token(
    client: Client, seeded: dict[str, Any], dashboard_token: Callable[..., str]
) -> None:
    """A series of P1 in another season is out of the season total."""
    from app.core.db import Session
    from app.models.match import Match
    from app.models.season import Season

    with Session() as session:
        other = Season(
            name="Season 2",
            number_weeks=4,
            series_per_week=2,
            start_date=date(2026, 3, 5),
            end_date=date(2026, 4, 27),
        )
        session.add(other)
        session.flush()
        match = Match(
            team1_id=seeded["team_a_id"],
            team2_id=seeded["team_b_id"],
            season_id=other.id,
            playday=1,
        )
        session.add(match)
        session.flush()
        other_match_id = match.id
        session.commit()

    add_series_for_player(
        other_match_id, seeded["player_ids"][0], seeded["player_ids"][2], 1
    )

    everything = client.get(f"/player-series?token={dashboard_token()}")
    assert everything.headers["X-Total-Count"] == "2"

    scoped = dashboard_token(season_id=seeded["season_id"])
    in_season = client.get(f"/player-series?token={scoped}")
    assert in_season.status_code == 200
    assert in_season.headers["X-Total-Count"] == "1"
    assert len(in_season.json()["series"]) == 1
