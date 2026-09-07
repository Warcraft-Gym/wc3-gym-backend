"""/veto and /announce: both post publicly, both refuse a series the caller
does not play, and both read the veto board the website runs."""

from datetime import UTC, datetime
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.series import Series
from tests.discord import CHANNEL, WEBHOOK, autocomplete, command, signed
from tests.test_series_veto import pool, taken, write  # noqa: F401  # pool is a fixture

SITE = "https://gnl.test"


def send(client: Client, payload: dict[str, Any]) -> Any:  # noqa: ANN401  # a JSON body
    body, headers = signed(payload)
    return client.post("/discord/interactions", content=body, headers=headers).json()


def test_veto_posts_the_board_link_and_the_state(
    client: Client,
    public_key: None,
    discord_calls: list,
    seeded: dict[str, Any],
    pool: list[int],  # noqa: F811  # the fixture of the veto tests
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRONTEND_URL", SITE)
    series_id = seeded["series_open_id"]
    assert send(client, command("veto", user="2", series=series_id)) == {"ok": True}
    (post, delete) = discord_calls
    assert post[:2] == ("POST", CHANNEL)
    assert post[2] == {
        "content": f"TBD · Wk 1 · P2 (Alpha) vs P4 (Beta) · #{series_id}\n"
        f"<@2> vs <@4> · veto 0/4, P2 to move\n"
        f"{SITE}/player-series/{series_id}/veto"
    }
    assert delete[:2] == ("DELETE", f"{WEBHOOK}/messages/@original")


def test_veto_says_complete_once_every_step_is_taken(
    client: Client,
    public_key: None,
    discord_calls: list,
    seeded: dict[str, Any],
    pool: list[int],  # noqa: F811  # the fixture of the veto tests
    dashboard_token: Any,  # noqa: ANN401  # a factory fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRONTEND_URL", SITE)
    series_id = seeded["series_open_id"]
    side_a, side_b = dashboard_token(discord_id="2"), dashboard_token(discord_id="4")
    taken(client, series_id, side_a, pool[1])
    taken(client, series_id, side_b, pool[2])
    # The last pick takes itself when one map is left, so three steps complete it
    taken(client, series_id, side_a, pool[3])
    send(client, command("veto", user="2", series=series_id))
    assert "· veto complete\n" in discord_calls[0][2]["content"]


def test_veto_names_the_website_without_a_frontend_url(
    client: Client,
    public_key: None,
    discord_calls: list,
    seeded: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    send(client, command("veto", user="2", series=seeded["series_open_id"]))
    assert discord_calls[0][2]["content"].endswith("The veto board is on the website.")


def test_announce_posts_the_match_card(
    client: Client,
    public_key: None,
    discord_calls: list,
    seeded: dict[str, Any],
    pool: list[int],  # noqa: F811  # the fixture of the veto tests
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRONTEND_URL", SITE)
    series_id = seeded["series_open_id"]
    when = datetime(2026, 9, 9, 20, tzinfo=UTC)
    with Session.begin() as session:
        series = session.get(Series, series_id)
        assert series
        series.date_time = when
        series.caster = "gnlcaster"
    assert send(client, command("announce", user="4", series=series_id)) == {"ok": True}
    (post, delete) = discord_calls
    assert post[:2] == ("POST", CHANNEL)
    stamp = int(when.timestamp())
    assert post[2] == {
        "content": "<@2> vs <@4>",
        "embeds": [
            {
                "title": "Wk 1 · P2 (Alpha) vs P4 (Beta)",
                "description": f"<t:{stamp}:F> (<t:{stamp}:R>)\n"
                "Cast on https://twitch.tv/gnlcaster\n"
                "veto 0/4, P2 to move\n"
                f"{SITE}/player-series/{series_id}/veto",
                "color": 0x4A4DB8,
            }
        ],
    }
    assert delete[:2] == ("DELETE", f"{WEBHOOK}/messages/@original")


def test_announce_says_when_a_series_has_no_time_yet(
    client: Client,
    public_key: None,
    discord_calls: list,
    seeded: dict[str, Any],
) -> None:
    send(client, command("announce", user="2", series=seeded["series_open_id"]))
    description = discord_calls[0][2]["embeds"][0]["description"]
    assert description.splitlines()[0] == "Not scheduled yet"


def test_both_commands_refuse_a_series_the_caller_does_not_play(
    client: Client,
    public_key: None,
    discord_calls: list,
    seeded: dict[str, Any],
) -> None:
    for name in ("veto", "announce"):
        send(client, command(name, user="1", series=seeded["series_open_id"]))
    edit = f"{WEBHOOK}/messages/@original"
    refusal = {"content": "not_authorized_for_this_series"}
    assert discord_calls == [("PATCH", edit, refusal), ("PATCH", edit, refusal)]


def test_both_commands_autocomplete_the_callers_own_series(
    client: Client, public_key: None, seeded: dict[str, Any]
) -> None:
    choice = {
        "name": f"Wk 1 · P2 (Alpha) vs P4 (Beta) · #{seeded['series_open_id']}",
        "value": seeded["series_open_id"],
    }
    for name in ("veto", "announce"):
        assert send(client, autocomplete(name, "2", "")) == {
            "type": 8,
            "data": {"choices": [choice]},
        }


def test_a_veto_step_edits_the_last_post_of_the_series(
    client: Client,
    public_key: None,
    discord_calls: list,
    seeded: dict[str, Any],
    pool: list[int],  # noqa: F811  # the fixture of the veto tests
    dashboard_token: Any,  # noqa: ANN401  # a factory fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRONTEND_URL", SITE)
    series_id = seeded["series_open_id"]
    send(client, command("veto", user="2", series=series_id))
    send(client, command("announce", user="4", series=series_id))
    discord_calls.clear()
    side_a = dashboard_token(discord_id="2")
    taken(client, series_id, side_a, pool[1])
    write(client, series_id, side_a, action="undo")
    edit = f"{CHANNEL}/msg-1"
    assert [call[:2] for call in discord_calls] == [("PATCH", edit), ("PATCH", edit)]
    # The newest post is the one edited: the /announce card, not the /veto line
    after_step, after_undo = (
        call[2]["embeds"][0]["description"] for call in discord_calls
    )
    assert "\nveto 1/4, P4 to move\n" in after_step
    assert "\nveto 0/4, P2 to move\n" in after_undo


def test_a_veto_step_without_a_post_calls_discord_not_at_all(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    pool: list[int],  # noqa: F811  # the fixture of the veto tests
    dashboard_token: Any,  # noqa: ANN401  # a factory fixture
) -> None:
    taken(client, seeded["series_open_id"], dashboard_token(discord_id="2"), pool[1])
    assert discord_calls == []
