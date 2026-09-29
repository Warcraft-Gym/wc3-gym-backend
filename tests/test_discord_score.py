"""/report-result reports a result from Discord: the attachments go to the bucket through the
presigned links, then the same write the dashboard uses applies the same rules."""

from typing import Any

import pytest
from httpx2 import Client

from app.services.commands import score
from tests.conftest import REPLAY_BYTES
from tests.discord import WEBHOOK, command, signed

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
    """A /report-result interaction carrying one attachment per game."""
    urls = {
        game_no: f"https://cdn.discord/att-{game_no}.w3g"
        for game_no in range(1, games + 1)
    }
    for game_no, url in urls.items():
        files[url] = (data or {}).get(game_no, REPLAY_BYTES)
    payload = command(
        "report-result",
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

    # The reply is private: the result card in the results channel is the announcement
    (reply,) = discord_calls
    assert reply[:2] == ("PATCH", EDIT)
    assert reply[2]["content"] == (
        "Reported: P2 2-1 P4. The result card is in the results channel."
    )


def refused(text: str) -> dict[str, Any]:
    """The private red card /report-result answers with."""
    return {
        "embeds": [
            {
                "title": "Error · result not saved",
                "description": text,
                "color": 0xED4245,
            }
        ]
    }


def test_an_incomplete_veto_saves_the_result_and_warns(
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

    reply = discord_calls[0]
    assert reply[:2] == ("PATCH", EDIT)
    posted = reply[2]["content"]
    assert "2-0" in posted
    assert "The map veto of this series is not complete" in posted
    assert f"https://gnl.test/player-series/{series_id}/veto" in posted

    # The result is saved, warning or not
    with Session() as session:
        series = session.get(Series, series_id)
        assert series and series.player1_score == 2
        assert session.get(DBSeriesReplay, (series_id, 1)) is not None


def saved_without(games: str) -> str:
    """The line the reply adds when games of the result have no replay."""
    return (
        f"No replay saved for {games}. The result is saved, and every game needs its"
        " replay: add it with Edit result on the website."
    )


def test_a_result_short_of_replays_saves_and_warns(
    client: Client,
    public_key: None,
    discord_calls: list,
    seeded: dict[str, Any],
    veto_done: None,
    attached: dict[str, bytes],
) -> None:
    """A 2-1 went three games; two files save the result and name the third game."""
    from app.core.db import Session
    from app.models.series import Series

    series_id = seeded["series_open_id"]
    send(client, scoring(attached, series_id, 2, 1, games=2))

    (reply,) = discord_calls
    assert reply[2]["content"].split("\n")[1:] == [saved_without("game 3")]
    with Session() as session:
        series = session.get(Series, series_id)
        assert series and (series.player1_score, series.player2_score) == (2, 1)


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


def test_a_file_that_is_not_a_replay_saves_the_result_without_it(
    client: Client,
    public_key: None,
    discord_calls: list,
    seeded: dict[str, Any],
    veto_done: None,
    attached: dict[str, bytes],
) -> None:
    from app.core.db import Session
    from app.models.series import Series
    from app.models.series_replay import DBSeriesReplay

    series_id = seeded["series_open_id"]
    send(client, scoring(attached, series_id, 2, 0, games=2, data={2: b"a text file"}))

    (reply,) = discord_calls
    assert reply[2]["content"].split("\n")[1:] == [saved_without("game 2")]
    with Session() as session:
        series = session.get(Series, series_id)
        assert series and series.player1_score == 2
        assert session.get(DBSeriesReplay, (series_id, 1)) is not None
        assert session.get(DBSeriesReplay, (series_id, 2)) is None


def test_a_file_over_ten_megabytes_is_left_out(
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
    (reply,) = discord_calls
    assert reply[2]["content"].split("\n")[1:] == [saved_without("game 1, game 2")]
    assert blob_store == {}


def test_the_command_asks_for_both_scores_and_offers_each_replay() -> None:
    """Discord refuses a missing required option before the interaction reaches
    us, so a replay option is never required: a result never waits on a file."""
    required = {
        option["name"]: option.get("required", False)
        for option in score.COMMAND["options"]
    }

    assert required == {
        "series": True,
        "player1_score": True,
        "player2_score": True,
        "game1": False,
        "game2": False,
        "game3": False,
    }
