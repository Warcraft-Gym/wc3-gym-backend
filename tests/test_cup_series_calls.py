"""A cup's draw, and every series set after it, ping the players who play.

They go to the cup's own thread in the announcement channel, opened under its
sign-up announcement, or under a quiet line of its own when it has none; a
thread Discord refuses leaves them in the channel. The draw lists each series
it set, with its two sides, the host (side 2, named second), a link to its veto
and last its game name, and pings those players instead of the announcement
role; a bye is named and pings nobody. A series a result completes later is
called once in a message of its own. A corrected result that changes a called
pairing rewrites the old message to say so, and the new pairing is called
again. A team cup pings each team's captain.
"""

from collections.abc import Callable
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.enums import StageFormat
from app.models.season import Season
from app.services import cup_announcements, discord
from tests.test_cup_announcements import ANNOUNCE, announcements, in_thread, thread_of
from tests.test_event_organizers import Headers
from tests.test_ffa import ffa, lobbies
from tests.test_stage_engine import bracket, cup, generate, score, team_cup

SITE = "https://cups.test"

__all__ = ["announcements"]


@pytest.fixture(autouse=True)
def site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRONTEND_URL", SITE)


def sent(calls: list[tuple[str, str, Any]]) -> list[dict[str, Any]]:
    """Every draw and series message of the cup's thread, in order, after the
    first, which says what the thread holds."""
    return in_thread(calls)[1:]


def lines_of(message: dict[str, Any]) -> list[str]:
    return message["embeds"][0]["description"].splitlines()


def in_channel(calls: list[tuple[str, str, Any]]) -> list[dict[str, Any]]:
    """Every message posted in the announcement channel itself, in order."""
    return [body for method, url, body in calls if (method, url) == ("POST", ANNOUNCE)]


def test_the_draw_opens_a_thread_under_the_sign_up_announcement(
    client: Client, auth_headers: Headers, discord_calls: list, announcements: None
) -> None:
    event, (stage,) = cup(4, best_of=3)
    with Session.begin() as session:
        row = session.get(Season, event)
        assert row is not None
        row.signups_open = True
    assert cup_announcements.announce_open(event)
    generate(client, auth_headers, event, stage)
    first, second = (row for row in bracket(stage) if row["round"] == "Semifinals")
    score(client, auth_headers, first["id"], 2, 0)
    score(client, auth_headers, second["id"], 2, 1)

    # the channel holds the sign-up announcement alone, and the thread hangs under it once
    assert len(in_channel(discord_calls)) == 1
    starts = [(url, body) for _, url, body in discord_calls if url.endswith("/threads")]
    assert starts == [
        (
            f"{ANNOUNCE}/msg-1/threads",
            {"name": "Autumn Cup", "auto_archive_duration": 10080},
        )
    ]
    head, draw, final = in_thread(discord_calls)
    assert head == {
        "content": "The draw and every series of **Autumn Cup** go here.",
        "allowed_mentions": {"parse": []},
    }
    assert draw["content"].startswith("The draw of **Autumn Cup** is out.")
    assert final["content"].startswith("**Final** of **Autumn Cup** is set.")


def test_a_cup_with_no_sign_up_announcement_hangs_its_thread_under_a_quiet_line(
    client: Client, auth_headers: Headers, discord_calls: list, announcements: None
) -> None:
    event, (stage,) = cup(4, best_of=3)
    generate(client, auth_headers, event, stage)

    assert in_channel(discord_calls) == [
        {
            "content": "**Autumn Cup**: its draw and every series follow in its thread.",
            "allowed_mentions": {"parse": []},
        }
    ]
    assert thread_of(discord_calls) == "msg-2"
    assert len(sent(discord_calls)) == 1


def test_a_refused_thread_leaves_the_draw_in_the_channel(
    client: Client,
    auth_headers: Headers,
    discord_calls: list,
    announcements: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Refused:
        ok, status_code = False, 403

        def json(self) -> dict[str, str]:
            return {}

    answer = discord._session.request

    # Discord opens no thread, and the anchor's id names none from before
    def request(method: str, url: str, **kwargs: Any) -> Any:  # noqa: ANN401
        if url.endswith("/threads") or "/channels/msg-1/" in url:
            discord_calls.append((method, url, kwargs.get("json")))
            return Refused()
        return answer(method, url, **kwargs)

    monkeypatch.setattr(discord._session, "request", request)
    event, (stage,) = cup(4, best_of=3)
    generate(client, auth_headers, event, stage)

    assert [body["content"].split("\n")[0] for body in in_channel(discord_calls)] == [
        "**Autumn Cup**: its draw and every series follow in its thread.",
        "The draw of **Autumn Cup** is out.",
    ]


def test_the_draw_lists_each_series_and_pings_its_players(
    client: Client, auth_headers: Headers, discord_calls: list, announcements: None
) -> None:
    event, (stage,) = cup(4, best_of=3)
    generate(client, auth_headers, event, stage)

    (draw,) = sent(discord_calls)
    pings = ["90001", "90004", "90002", "90003"]
    assert draw["content"] == "The draw of **Autumn Cup** is out.\n" + " ".join(
        f"<@{ping}>" for ping in pings
    )
    assert sorted(draw["allowed_mentions"]["users"]) == sorted(pings)
    semis = [row for row in bracket(stage) if row["round"] == "Semifinals"]
    assert lines_of(draw) == [
        (
            "**E1** vs **E4** (hosts) · "
            f"[Veto]({SITE}/events/{event}?tab=draw&veto={semis[0]['id']}) · "
            f"Game Name: `GYM_{semis[0]['id']}`"
        ),
        (
            "**E2** vs **E3** (hosts) · "
            f"[Veto]({SITE}/events/{event}?tab=draw&veto={semis[1]['id']}) · "
            f"Game Name: `GYM_{semis[1]['id']}`"
        ),
    ]
    # the event page reads the same game name and host
    read = client.get(f"/cup-series/{semis[0]['id']}").json()
    assert (read["game_name"], read["host_side"]) == (f"GYM_{semis[0]['id']}", 2)


def test_a_lobby_names_its_seats_its_map_and_last_its_game_name(
    client: Client, auth_headers: Headers, discord_calls: list, announcements: None
) -> None:
    event, heats, _ = ffa(8)
    generate(client, auth_headers, event, heats)

    (draw,) = sent(discord_calls)
    lobby = lobbies(client, event, heats, "Round 1")[0]
    game = f" · Game Name: `GYM_{lobby['id']}`"
    (line,) = (line for line in lines_of(draw) if line.endswith(game))
    # the last seat hosts, then the map and the draw, as the head to head lines
    seats, *rest = line.split(" · ")
    assert seats.endswith("** (hosts)")
    assert " · ".join(rest) == (
        f"{lobby['lobby_map']['name']} · [Open]({SITE}/events/{event}?tab=draw)" + game
    )


def test_a_bye_is_named_and_pings_nobody(
    client: Client, auth_headers: Headers, discord_calls: list, announcements: None
) -> None:
    # a double elimination pads three players to four, and the padded pair is a walkover
    event, (stage,) = cup(3, StageFormat.double_elimination, best_of=3)
    generate(client, auth_headers, event, stage)

    (draw,) = sent(discord_calls)
    assert "**E1** · bye" in lines_of(draw)
    assert sorted(draw["allowed_mentions"]["users"]) == ["90002", "90003"]


def test_a_later_series_is_called_once_both_its_sides_stand(
    client: Client, auth_headers: Headers, discord_calls: list, announcements: None
) -> None:
    event, (stage,) = cup(4, best_of=3)
    generate(client, auth_headers, event, stage)
    first, second = (row for row in bracket(stage) if row["round"] == "Semifinals")

    assert score(client, auth_headers, first["id"], 2, 0).status_code == 200
    # the final still waits for its second side
    assert len(sent(discord_calls)) == 1
    assert score(client, auth_headers, second["id"], 2, 1).status_code == 200

    final = sent(discord_calls)[-1]
    assert final["content"] == "**Final** of **Autumn Cup** is set.\n<@90001> <@90002>"
    (line,) = lines_of(final)
    (decider,) = (row for row in bracket(stage) if row["round"] == "Final")
    assert line.startswith("**E1** vs **E2** (hosts)")
    assert line.endswith(f" · Game Name: `GYM_{decider['id']}`")
    # a fix that keeps the winner calls nothing again
    assert score(client, auth_headers, second["id"], 2, 0).status_code == 200
    assert len(sent(discord_calls)) == 2


def test_a_corrected_pairing_is_marked_replaced_and_called_again(
    client: Client, auth_headers: Headers, discord_calls: list, announcements: None
) -> None:
    event, (stage,) = cup(4, best_of=3)
    generate(client, auth_headers, event, stage)
    first, second = (row for row in bracket(stage) if row["round"] == "Semifinals")
    score(client, auth_headers, first["id"], 2, 0)
    score(client, auth_headers, second["id"], 2, 1)

    turned = score(client, auth_headers, second["id"], 1, 2)

    assert turned.status_code == 200, turned.text
    edits = [body for method, _, body in discord_calls if method == "PATCH"]
    assert edits and edits[-1]["content"].startswith("A corrected result changed")
    assert edits[-1]["embeds"] == []
    # the edit finds the message in the cup's thread
    (patched,) = {url for method, url, _ in discord_calls if method == "PATCH"}
    assert patched.startswith(
        f"{discord.API_URL}/channels/{thread_of(discord_calls)}/messages/"
    )
    again = sent(discord_calls)[-1]
    assert again["content"] == "**Final** of **Autumn Cup** is set.\n<@90001> <@90003>"


def test_a_team_cup_pings_each_teams_captain(
    client: Client,
    auth_headers: Headers,
    member: Callable[..., dict[str, str]],
    discord_calls: list,
    announcements: None,
) -> None:
    event, stage, _, tags = team_cup(client, auth_headers, member)
    generate(client, auth_headers, event, stage)

    (draw,) = sent(discord_calls)
    captains = {roster[0] for roster in tags}
    assert set(draw["allowed_mentions"]["users"]) == captains
    assert all("**T" in line for line in lines_of(draw))
