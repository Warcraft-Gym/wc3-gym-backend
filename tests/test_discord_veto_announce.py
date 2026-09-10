"""/veto and /announce: both post publicly, both refuse a series the caller
does not play, and both read the veto board the website runs."""

from datetime import UTC, datetime
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.season import Season
from app.models.series import Series
from app.models.series_cast import SeriesCast
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
        # Only the player whose turn it is gets the tag
        "content": "TBD · Round 1 · P2 (Alpha) vs P4 (Beta)\n"
        "<@2> · veto 0/4, P2 to ban\nFixed map · Concealed Hill\n"
        f"{SITE}/player-series/{series_id}/veto"
    }
    assert delete[:2] == ("DELETE", f"{WEBHOOK}/messages/@original")


def test_veto_says_complete_once_every_step_is_taken(
    client: Client,
    public_key: None,
    discord_calls: list,
    seeded: dict[str, Any],
    pool: list[int],  # noqa: F811  # the fixture of the veto tests
    member: Any,  # noqa: ANN401  # a factory fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRONTEND_URL", SITE)
    series_id = seeded["series_open_id"]
    side_a, side_b = member("2"), member("4")
    taken(client, series_id, side_a, pool[1])
    taken(client, series_id, side_b, pool[2])
    # The last pick takes itself when one map is left, so three steps complete it
    taken(client, series_id, side_a, pool[3])
    send(client, command("veto", user="2", series=series_id))
    assert (
        # A complete veto has nobody to tag
        "\nveto complete\nFixed map · Concealed Hill\nBan · EI · P2\nBan · TS · P4\n"
        "Pick · LR · P2\nPick · AL · P4\n"
    ) in discord_calls[0][2]["content"]


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
        series.casts.append(SeriesCast(channel_url="https://www.twitch.tv/gnlcaster"))
    assert send(client, command("announce", user="4", series=series_id)) == {"ok": True}
    (post, delete) = discord_calls
    assert post[:2] == ("POST", CHANNEL)
    stamp = int(when.timestamp())
    # Round 1 runs 5 to 11 January 2026; each date is noon UTC
    first, last = (
        int(datetime(2026, 1, d, 12, tzinfo=UTC).timestamp()) for d in (5, 11)
    )
    assert post[2] == {
        "content": "<@2> vs <@4>",
        "embeds": [
            {
                "description": "## Season 1\n"
                f"Round 1: <t:{first}:d> to <t:{last}:d>\n\n"
                "### Team Alpha (Alpha) vs Team Beta (Beta)\n"
                f"🇺🇸 **[P2](<{SITE}/player/P2%232222>)** vs "
                f"🇸🇪 **[P4](<{SITE}/player/P4%234444>)**\n"
                f"<t:{stamp}:F> · <t:{stamp}:R>\n\n"
                "**Veto**\n"
                "Game 1 · Concealed Hill, fixed map\n"
                "Game 2 · loser of game 1 picks\n"
                "Game 3 · loser of game 2 picks\n"
                "Picks · P2: not picked yet · P4: not picked yet\n"
                "Veto 0/4, P2 to ban\n"
                f"[Veto board](<{SITE}/player-series/{series_id}/veto>)\n\n"
                "**Casts**\n"
                "- <https://www.twitch.tv/gnlcaster> · twitch.tv/gnlcaster",
                "color": 0x4A4DB8,
                "footer": {"text": "MMR not synced yet"},
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
    assert "Not scheduled yet" in description.splitlines()


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
        "name": f"Round 1 · P2 (Alpha) vs P4 (Beta) · #{seeded['series_open_id']}",
        "value": seeded["series_open_id"],
    }
    for name in ("veto", "announce"):
        assert send(client, autocomplete(name, "2", "")) == {
            "type": 8,
            "data": {"choices": [choice]},
        }


def test_a_veto_step_edits_every_post_of_the_series(
    client: Client,
    public_key: None,
    discord_calls: list,
    seeded: dict[str, Any],
    pool: list[int],  # noqa: F811  # the fixture of the veto tests
    member: Any,  # noqa: ANN401  # a factory fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRONTEND_URL", SITE)
    series_id = seeded["series_open_id"]
    send(client, command("veto", user="2", series=series_id))
    send(client, command("announce", user="4", series=series_id))
    discord_calls.clear()
    side_a = member("2")
    taken(client, series_id, side_a, pool[1])
    write(client, series_id, side_a, action="undo")
    veto_post, announce_post = f"{CHANNEL}/msg-1", f"{CHANNEL}/msg-2"
    assert [call[:2] for call in discord_calls] == [
        ("PATCH", veto_post),
        ("PATCH", announce_post),
        ("PATCH", veto_post),
        ("PATCH", announce_post),
    ]
    step = "veto 1/4, P4 to ban\nFixed map · Concealed Hill\nBan · EI · P2\n"
    undone = "veto 0/4, P2 to ban\nFixed map · Concealed Hill\n"
    assert f"· {step}" in discord_calls[0][2]["content"]
    # The match card sums the veto up in one line: how far it is and whose turn
    assert "\nVeto 1/4, P4 to ban\n" in discord_calls[1][2]["embeds"][0]["description"]
    assert f"· {undone}" in discord_calls[2][2]["content"]
    assert "\nVeto 0/4, P2 to ban\n" in discord_calls[3][2]["embeds"][0]["description"]


def test_a_new_time_edits_the_announce_card(
    client: Client,
    public_key: None,
    discord_calls: list,
    seeded: dict[str, Any],
    pool: list[int],  # noqa: F811  # the fixture of the veto tests
) -> None:
    series_id = seeded["series_open_id"]
    send(client, command("announce", user="4", series=series_id))
    discord_calls.clear()
    send(
        client,
        command("schedule", user="2", series=series_id, when_utc="2026-09-09 20:00"),
    )
    edit = next(call for call in discord_calls if call[0] == "PATCH")
    stamp = int(datetime(2026, 9, 9, 20, tzinfo=UTC).timestamp())
    assert edit[1] == f"{CHANNEL}/msg-1"
    assert f"\n<t:{stamp}:F> · <t:{stamp}:R>\n" in edit[2]["embeds"][0]["description"]


def test_a_veto_step_without_a_post_calls_discord_not_at_all(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    pool: list[int],  # noqa: F811  # the fixture of the veto tests
    member: Any,  # noqa: ANN401  # a factory fixture
) -> None:
    taken(client, seeded["series_open_id"], member("2"), pool[1])
    assert discord_calls == []


def test_the_card_follows_the_seasons_map_rules(
    client: Client,
    public_key: None,
    discord_calls: list,
    seeded: dict[str, Any],
    pool: list[int],  # noqa: F811  # the fixture of the veto tests
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A season without the week rule has no fixed map, so the card has no
    fixed map line; the card carries no rule wording of its own."""
    monkeypatch.setenv("FRONTEND_URL", SITE)
    series_id = seeded["series_open_id"]
    with Session.begin() as session:
        season = session.get(Season, seeded["season_id"])
        assert season
        season.map_rules = "veto,loser"
    send(client, command("veto", user="2", series=series_id))
    content = discord_calls[0][2]["content"]
    assert f"· veto 0/4, P2 to ban\n{SITE}" in content
    assert "Fixed map" not in content
