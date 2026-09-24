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
    assert len(purges) == 1
    call = purges[0]
    assert call["in_request"], "sent by the middleware after the response"
    assert call["url"] == edge_purge.API_URL
    assert call["params"] == {"projectIdOrName": "test-project"}
    assert call["headers"] == {"Authorization": "Bearer test-purge-token"}
    assert f"event-{seeded['season_id']}" in call["json"]["tags"]
    assert {"home", "career"} <= set(call["json"]["tags"])


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
    assert len(purges) == 1
    assert f"event-{seeded['season_id']}" in purges[0]["json"]["tags"]


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
    edge_purge.send([f"t{n}" for n in range(20)])
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
