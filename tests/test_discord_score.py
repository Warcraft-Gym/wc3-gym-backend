"""/score reports a result from Discord: the attachments go to the bucket through the
presigned links, then the same write the dashboard uses applies the same rules."""

from typing import Any

import pytest
from httpx2 import Client

from app.services.commands import score
from tests.conftest import REPLAY_BYTES
from tests.discord import CHANNEL, WEBHOOK, command, signed

EDIT = f"{WEBHOOK}/messages/@original"


@pytest.fixture
def veto_order(seeded: dict[str, Any]) -> None:
    """A season with a one step veto, so the board can be complete or not."""
    from app.core.db import Session
    from app.models.season import Season

    with Session.begin() as session:
        season = session.get(Season, seeded["season_id"])
        assert season
        season.pick_ban = "Ban_A"


@pytest.fixture
def veto_done(seeded: dict[str, Any], veto_order: None) -> None:
    """Side A bans the one map of the pool, which completes that order."""
    from app.services.series_veto import SeriesVetoService

    SeriesVetoService().take(
        seeded["series_open_id"],
        seeded["player_ids"][1],
        "step",
        seeded["map_id"],
    )


@pytest.fixture
def attached(
    monkeypatch: pytest.MonkeyPatch, blob_store: dict[str, bytes]
) -> dict[str, bytes]:
    """Discord serves these bytes per attachment URL, and a PUT lands in the fake bucket."""
    files: dict[str, bytes] = {}

    class Answer:
        def __init__(self, content: bytes = b"") -> None:
            self.content = content

        def raise_for_status(self) -> None:
            return None

    def get(url: str, **kwargs: object) -> Answer:
        return Answer(files[url])

    def put(url: str, data: bytes = b"", **kwargs: object) -> Answer:
        # the fake upload_url is the fake download_url with /upload/ in front of the key
        blob_store[f"https://r2.test/{url.split('/upload/', 1)[1]}"] = data
        return Answer()

    monkeypatch.setattr(score.requests, "get", get)
    monkeypatch.setattr(score.requests, "put", put)
    return files


def scoring(
    files: dict[str, bytes],
    series_id: int,
    p1: int,
    p2: int,
    user: str = "2",
    games: int = 3,
    size: int = 1024,
    data: dict[int, bytes] | None = None,
) -> dict[str, Any]:
    """A /score interaction carrying one attachment per game."""
    urls = {
        game_no: f"https://cdn.discord/att-{game_no}.w3g"
        for game_no in range(1, games + 1)
    }
    for game_no, url in urls.items():
        files[url] = (data or {}).get(game_no, REPLAY_BYTES)
    payload = command(
        "score",
        user=user,
        series=series_id,
        player1_score=p1,
        player2_score=p2,
        **{f"game{game_no}": f"att-{game_no}" for game_no in urls},
    )
    payload["data"]["resolved"] = {
        "attachments": {
            f"att-{game_no}": {
                "url": url,
                "filename": f"game{game_no}.w3g",
                "size": size,
            }
            for game_no, url in urls.items()
        }
    }
    return payload


def send(client: Client, payload: dict[str, Any]) -> None:
    body, headers = signed(payload)
    resp = client.post("/discord/interactions", content=body, headers=headers)
    assert resp.status_code == 200, resp.text


def test_a_player_reports_the_result_and_its_replays(
    client: Client,
    public_key: None,
    discord_calls: list,
    seeded: dict[str, Any],
    veto_done: None,
    attached: dict[str, bytes],
    blob_store: dict[str, bytes],
) -> None:
    from app.core.db import Session
    from app.models.series import Series

    series_id = seeded["series_open_id"]
    send(client, scoring(attached, series_id, 2, 1))

    with Session() as session:
        series = session.get(Series, series_id)
        assert series and (series.player1_score, series.player2_score) == (2, 1)
    assert [
        blob_store[f"https://r2.test/development/replays/{series_id}/game{n}.w3g"]
        for n in (1, 2, 3)
    ] == [REPLAY_BYTES] * 3

    (post, delete) = discord_calls
    assert post[:2] == ("POST", CHANNEL)
    assert post[2]["content"].splitlines() == [
        f"Result by <@2>: P2 2-1 P4 · Wk 1 · #{series_id}",
        f"Game 1: https://r2.test/development/replays/{series_id}/game1.w3g",
        f"Game 2: https://r2.test/development/replays/{series_id}/game2.w3g",
        f"Game 3: https://r2.test/development/replays/{series_id}/game3.w3g",
    ]
    assert delete[:2] == ("DELETE", EDIT)


def refused(text: str) -> dict[str, Any]:
    """The private red card /score answers with."""
    return {
        "embeds": [
            {
                "title": "Error · result not saved",
                "description": text,
                "color": 0xED4245,
            }
        ]
    }


def test_an_incomplete_veto_answers_the_board_link(
    client: Client,
    public_key: None,
    discord_calls: list,
    seeded: dict[str, Any],
    veto_order: None,
    attached: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.db import Session
    from app.models.series import Series
    from app.models.series_replay import DBSeriesReplay

    monkeypatch.setenv("FRONTEND_URL", "https://gnl.test/")
    series_id = seeded["series_open_id"]
    send(client, scoring(attached, series_id, 2, 0, games=2))

    assert discord_calls == [
        (
            "PATCH",
            EDIT,
            refused(
                "The map veto is not complete, so the result cannot be saved. Enter the"
                f" veto on the [veto board](https://gnl.test/player-series/{series_id}/veto)"
                " first. Then report the score here, or in Report Result on"
                " [your dashboard](https://gnl.test/player-dashboard)."
            ),
        )
    ]
    with Session() as session:
        series = session.get(Series, series_id)
        assert series and series.player1_score is None
        assert session.get(DBSeriesReplay, (series_id, 1)) is None


def test_the_attachments_must_match_the_games_played(
    client: Client,
    public_key: None,
    discord_calls: list,
    seeded: dict[str, Any],
    veto_done: None,
    attached: dict[str, bytes],
    blob_store: dict[str, bytes],
) -> None:
    send(client, scoring(attached, seeded["series_open_id"], 2, 1, games=2))
    assert discord_calls == [
        (
            "PATCH",
            EDIT,
            refused(
                "Attach one replay per game played: a 2-1 result needs 3 files, game1 to"
                " game3. The score is saved only when the replays match it."
            ),
        )
    ]
    assert blob_store == {}


def test_a_stranger_is_refused(
    client: Client,
    public_key: None,
    discord_calls: list,
    seeded: dict[str, Any],
    veto_done: None,
    attached: dict[str, bytes],
    blob_store: dict[str, bytes],
) -> None:
    send(client, scoring(attached, seeded["series_open_id"], 2, 0, user="1", games=2))
    assert discord_calls == [
        ("PATCH", EDIT, refused("Only a player of the series can report its result."))
    ]
    assert blob_store == {}


def test_a_file_that_is_not_a_replay_is_refused(
    client: Client,
    public_key: None,
    discord_calls: list,
    seeded: dict[str, Any],
    veto_done: None,
    attached: dict[str, bytes],
) -> None:
    from app.core.db import Session
    from app.models.series import Series

    series_id = seeded["series_open_id"]
    send(client, scoring(attached, series_id, 2, 0, games=2, data={2: b"a text file"}))
    assert discord_calls == [
        ("PATCH", EDIT, refused("Game 2 is not a Warcraft III replay"))
    ]
    with Session() as session:
        series = session.get(Series, series_id)
        assert series and series.player1_score is None


def test_a_file_over_ten_megabytes_is_refused(
    client: Client,
    public_key: None,
    discord_calls: list,
    seeded: dict[str, Any],
    veto_done: None,
    attached: dict[str, bytes],
    blob_store: dict[str, bytes],
) -> None:
    send(
        client,
        scoring(attached, seeded["series_open_id"], 2, 0, games=2, size=11 * 1024**2),
    )
    assert discord_calls == [("PATCH", EDIT, refused("Replay 1 is over 10 MB."))]
    assert blob_store == {}
