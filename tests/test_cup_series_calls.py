"""A cup's draw, and every series set after it, ping the players who play.

The draw lists each series it set, with its game name, its two sides, the host
(side 2, named second) and a link to its veto, and pings those players instead
of the announcement role; a bye is named and pings nobody. A series a result
completes later is called once in a message of its own. A corrected result that
changes a called pairing rewrites the old message to say so, and the new pairing
is called again. A team cup pings each team's captain.
"""

from collections.abc import Callable
from typing import Any

import pytest
from httpx2 import Client

from app.models.enums import StageFormat
from tests.test_cup_announcements import ANNOUNCE, announcements
from tests.test_event_organizers import Headers
from tests.test_stage_engine import bracket, cup, generate, score, team_cup

SITE = "https://cups.test"

__all__ = ["announcements"]


@pytest.fixture(autouse=True)
def site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRONTEND_URL", SITE)


def sent(calls: list[tuple[str, str, Any]]) -> list[dict[str, Any]]:
    """Every message posted in the announcement channel, in order."""
    return [body for method, url, body in calls if (method, url) == ("POST", ANNOUNCE)]


def lines_of(message: dict[str, Any]) -> list[str]:
    return message["embeds"][0]["description"].splitlines()


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
            f"`GYM {semis[0]['id']}` · **E1** vs **E4** (hosts) · "
            f"[Veto]({SITE}/events/{event}?tab=draw&veto={semis[0]['id']})"
        ),
        (
            f"`GYM {semis[1]['id']}` · **E2** vs **E3** (hosts) · "
            f"[Veto]({SITE}/events/{event}?tab=draw&veto={semis[1]['id']})"
        ),
    ]
    # the event page reads the same game name and host
    read = client.get(f"/cup-series/{semis[0]['id']}").json()
    assert (read["game_name"], read["host_side"]) == (f"GYM {semis[0]['id']}", 2)


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
    assert line.startswith("`GYM ") and "**E1** vs **E2** (hosts)" in line
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
