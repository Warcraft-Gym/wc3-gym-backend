"""A write clears the edge copies of the reads it changes, after the response."""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from httpx2 import Client

from app.services import edge_purge


class Sent:
    status_code = 200

    def raise_for_status(self) -> None:
        pass


@pytest.fixture
def purges(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    """Configure the purge and record each call it sends to Vercel."""
    calls: list[dict[str, Any]] = []

    def post(url: str, **kwargs: Any) -> Sent:  # noqa: ANN401
        # the middleware sends inside the request; a commit outside one sends at once
        calls.append(
            {"url": url, "in_request": edge_purge._pending.get() is not None, **kwargs}
        )
        return Sent()

    monkeypatch.setenv("VERCEL_CACHE_TOKEN", "test-purge-token")
    monkeypatch.setenv("VERCEL_PROJECT_ID", "test-project")
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    monkeypatch.setattr(edge_purge.requests, "post", post)
    edge_purge._config.cache_clear()
    yield calls
    edge_purge._config.cache_clear()


def by_url(calls: list[dict[str, Any]]) -> dict[str, list[str]]:
    """The tags each endpoint was sent, one call per endpoint."""
    assert len({call["url"] for call in calls}) == len(calls), calls
    return {call["url"]: call["json"]["tags"] for call in calls}


@pytest.fixture
def pending() -> Iterator[set[str]]:
    """The set a request collects its tags in, outside any request."""
    tags: set[str] = set()
    token = edge_purge._pending.set(tags)
    yield tags
    edge_purge._pending.reset(token)


def test_a_result_report_clears_its_event_once(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    replay_uploaded: Callable[..., None],
    purges: list[dict[str, Any]],
) -> None:
    series_id = seeded["series_open_id"]
    side_a = member("2")
    replay_uploaded(series_id, 1, 2)
    scores = {"action": "score_updated", "player1_score": "2", "player2_score": "0"}
    purges.clear()
    resp = client.put(f"/player-series/{series_id}", data=scores, headers=side_a)
    assert resp.status_code == 200, resp.text
    # the event copy is deleted, the global lists are invalidated: one call each
    assert by_url(purges) == {
        edge_purge.DELETE: [f"event-{seeded['season_id']}"],
        edge_purge.INVALIDATE: ["career", "home"],
    }
    for call in purges:
        assert call["in_request"], "sent by the middleware after the response"
        assert call["params"] == {"projectIdOrName": "test-project"}
        assert call["headers"] == {"Authorization": "Bearer test-purge-token"}


def test_an_admin_series_edit_clears_its_event_once(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    purges: list[dict[str, Any]],
) -> None:
    series_id = seeded["series_open_id"]
    answer = client.get(f"/series/{series_id}").json()
    answer["date_time"] = "2026-09-05T18:00:00Z"
    purges.clear()
    resp = client.put(f"/series/{series_id}", json=answer, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    # a booking moves no career total
    assert by_url(purges) == {
        edge_purge.DELETE: [f"event-{seeded['season_id']}"],
        edge_purge.INVALIDATE: ["home"],
    }


def test_a_read_clears_nothing(
    client: Client, seeded: dict[str, Any], purges: list[dict[str, Any]]
) -> None:
    purges.clear()
    resp = client.get(f"/events/{seeded['season_id']}/series")
    assert resp.status_code == 200, resp.text
    assert purges == []


def test_a_rollback_clears_nothing(
    seeded: dict[str, Any], purges: list[dict[str, Any]], pending: set[str]
) -> None:
    from app.core.db import Session
    from app.models.series import Series

    with pytest.raises(RuntimeError), Session.begin() as session:
        series = session.get(Series, seeded["series_open_id"])
        assert series is not None
        series.player1_score = 1
        session.flush()
        raise RuntimeError
    assert pending == set()
    assert purges == []


def test_the_commit_hands_the_tags_to_the_request(
    seeded: dict[str, Any], purges: list[dict[str, Any]], pending: set[str]
) -> None:
    from app.core.db import Session
    from app.models.series import Series

    with Session.begin() as session:
        series = session.get(Series, seeded["series_open_id"])
        assert series is not None
        series.player1_score = 1
    assert pending == {f"event-{seeded['season_id']}", "home", "career"}
    assert purges == []


def edit_series(series_id: int, **fields: Any) -> None:  # noqa: ANN401
    from app.core.db import Session
    from app.models.series import Series

    with Session.begin() as session:
        series = session.get(Series, series_id)
        assert series is not None
        for name, value in fields.items():
            setattr(series, name, value)


def test_a_booking_clears_no_career_and_a_score_does(
    seeded: dict[str, Any], purges: list[dict[str, Any]], pending: set[str]
) -> None:
    from datetime import UTC, datetime

    event = f"event-{seeded['season_id']}"
    edit_series(
        seeded["series_open_id"], date_time=datetime(2026, 9, 5, 18, tzinfo=UTC)
    )
    assert pending == {event, "home"}
    pending.clear()
    edit_series(seeded["series_open_id"], player1_score=2, player2_score=0)
    assert pending == {event, "home", "career"}


def test_a_moved_series_clears_its_old_event_and_its_new_one(
    seeded: dict[str, Any], purges: list[dict[str, Any]], pending: set[str]
) -> None:
    from app.core.db import Session
    from app.models.match import Match
    from tests.test_events import add_event

    other = add_event(published=True)
    with Session.begin() as session:
        match = Match(
            team1_id=seeded["team_a_id"],
            team2_id=seeded["team_b_id"],
            season_id=other,
            playday=1,
        )
        session.add(match)
        session.flush()
        match_id = match.id
    pending.clear()
    edit_series(seeded["series_open_id"], match_id=match_id)
    assert {f"event-{seeded['season_id']}", f"event-{other}"} <= pending


def test_a_player_rename_clears_the_lists_and_the_events_he_plays_in(
    seeded: dict[str, Any], purges: list[dict[str, Any]], pending: set[str]
) -> None:
    from app.core.db import Session
    from app.models.user import User

    with Session.begin() as session:
        user = session.get(User, seeded["player_ids"][0])
        assert user is not None
        user.name = "Renamed"
    assert pending == {f"event-{seeded['season_id']}", "home", "career", "ladder"}


def test_a_map_rename_clears_the_events_that_use_it(
    seeded: dict[str, Any], purges: list[dict[str, Any]], pending: set[str]
) -> None:
    from sqlmodel import select

    from app.core.db import Session
    from app.models.map import Map

    with Session.begin() as session:
        game_map = session.scalars(select(Map)).one()
        game_map.name = "Renamed"
    assert pending == {f"event-{seeded['season_id']}"}


def test_a_bulk_statement_names_its_tags(
    seeded: dict[str, Any], purges: list[dict[str, Any]], pending: set[str]
) -> None:
    from app.api.deps import season_service
    from app.services import series_games

    event = f"event-{seeded['season_id']}"
    season_service.set_achievements(seeded["season_id"], [])
    assert pending == {event, "ladder"}
    pending.clear()
    # a bulk delete of the games, with no game written after it
    series_games.record(seeded["series_played_id"], [])
    assert pending == {event, "home", "career"}


def test_a_failed_tag_lookup_never_fails_the_write(
    seeded: dict[str, Any],
    purges: list[dict[str, Any]],
    pending: set[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.db import Session
    from app.models.series import Series

    def broken(*args: object) -> set[str]:
        raise RuntimeError

    monkeypatch.setattr(edge_purge, "tags_of", broken)
    edit_series(seeded["series_open_id"], player1_score=1)
    with Session.begin() as session:
        series = session.get(Series, seeded["series_open_id"])
        assert series is not None
        assert series.player1_score == 1
    assert pending == set()


def test_with_no_token_nothing_is_sent(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    purges: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VERCEL_CACHE_TOKEN")
    edge_purge._config.cache_clear()
    series_id = seeded["series_open_id"]
    answer = client.get(f"/series/{series_id}").json()
    answer["date_time"] = "2026-09-05T18:00:00Z"
    resp = client.put(f"/series/{series_id}", json=answer, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert purges == []


def test_a_failed_call_never_fails_the_write(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    purges: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def down(url: str, **kwargs: Any) -> Sent:  # noqa: ANN401
        raise ConnectionError

    monkeypatch.setattr(edge_purge.requests, "post", down)
    series_id = seeded["series_open_id"]
    answer = client.get(f"/series/{series_id}").json()
    answer["date_time"] = "2026-09-05T18:00:00Z"
    resp = client.put(f"/series/{series_id}", json=answer, headers=auth_headers)
    assert resp.status_code == 200, resp.text


def test_a_preview_write_clears_the_preview_copies(
    purges: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERCEL_ENV", "preview")
    monkeypatch.setenv("VERCEL_TEAM_ID", "test-team")
    edge_purge._config.cache_clear()
    edge_purge.send([f"event-{n}" for n in range(20)])
    assert [len(call["json"]["tags"]) for call in purges] == [16, 4]
    assert {call["json"]["target"] for call in purges} == {"preview"}
    assert purges[0]["params"]["teamId"] == "test-team"


def test_a_team_rename_clears_the_events_it_plays_in(
    seeded: dict[str, Any], purges: list[dict[str, Any]], pending: set[str]
) -> None:
    from app.core.db import Session
    from app.models.team import Team

    with Session.begin() as session:
        team = session.get(Team, seeded["team_a_id"])
        assert team is not None
        team.name = "Renamed"
    assert pending == {f"event-{seeded['season_id']}", "home"}
