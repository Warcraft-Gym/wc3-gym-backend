"""A member claims a series to cast, edits and removes its own claim only.

The claim rides on the series answer as `casts`, so every series table
shows it with no second read.
"""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from tests.conftest import Client
from tests.migrate import fresh_database, upgrade_to
from tests.test_discord_auth import SESSION, stub_clerk

TWITCH = "https://www.twitch.tv/gnlcaster"


def as_member(monkeypatch: pytest.MonkeyPatch, discord_id: str) -> None:
    """A Clerk session of the seeded player with that Discord id."""
    stub_clerk(monkeypatch, account={"id": discord_id, "username": f"p{discord_id}"})


def test_a_member_claims_edits_and_unclaims(
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    series_id = seeded["series_open_id"]
    as_member(monkeypatch, "1")
    resp = client.post(
        f"/series/{series_id}/casts",
        json={"channel_url": "twitch.tv/gnlcaster"},
        headers=SESSION,
    )
    assert resp.status_code == 201, resp.text
    (cast,) = resp.json()
    assert cast["name"] == "P1"
    assert cast["channel_url"] == "https://twitch.tv/gnlcaster"
    assert cast["user_id"] == seeded["player_ids"][0]

    # The series carries its casts, and the newest claim pre-fills the next
    assert client.get(f"/series/{series_id}").json()["casts"] == [cast]
    assert client.get("/casts/last", headers=SESSION).json() == {
        "channel_url": "https://twitch.tv/gnlcaster"
    }

    resp = client.post(
        f"/series/{series_id}/casts", json={"channel_url": TWITCH}, headers=SESSION
    )
    assert resp.status_code == 400
    assert resp.json() == {"error": "You already cast this series"}

    resp = client.put(
        f"/series/{series_id}/casts/{cast['id']}",
        json={"channel_url": TWITCH},
        headers=SESSION,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["channel_url"] == TWITCH

    resp = client.delete(f"/series/{series_id}/casts/{cast['id']}", headers=SESSION)
    assert resp.status_code == 204
    assert client.get(f"/series/{series_id}/casts").json() == []


def test_another_member_sees_the_cast_and_cannot_touch_it(
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    series_id = seeded["series_open_id"]
    as_member(monkeypatch, "1")
    (cast,) = client.post(
        f"/series/{series_id}/casts", json={"channel_url": TWITCH}, headers=SESSION
    ).json()

    as_member(monkeypatch, "2")
    assert client.get(f"/series/{series_id}/casts").json() == [cast]
    resp = client.put(
        f"/series/{series_id}/casts/{cast['id']}",
        json={"channel_url": TWITCH},
        headers=SESSION,
    )
    assert resp.status_code == 403
    assert (
        client.delete(
            f"/series/{series_id}/casts/{cast['id']}", headers=SESSION
        ).status_code
        == 403
    )
    # A second caster on the same series is allowed
    resp = client.post(
        f"/series/{series_id}/casts",
        json={"channel_url": "https://youtube.com/@p2/live"},
        headers=SESSION,
    )
    assert resp.status_code == 201, resp.text
    assert [c["name"] for c in resp.json()] == ["P1", "P2"]


def test_an_admin_removes_any_cast(
    client: Client,
    seeded: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    auth_headers: dict[str, str],
) -> None:
    series_id = seeded["series_open_id"]
    as_member(monkeypatch, "1")
    (cast,) = client.post(
        f"/series/{series_id}/casts", json={"channel_url": TWITCH}, headers=SESSION
    ).json()
    # The admin token has no player row, so it grants an admin with one
    client.post("/config/admins", json={"discord_id": "2"}, headers=auth_headers)
    as_member(monkeypatch, "2")
    assert (
        client.delete(
            f"/series/{series_id}/casts/{cast['id']}", headers=SESSION
        ).status_code
        == 204
    )


@pytest.mark.parametrize(
    "url", ["", "gnlcaster", "https://twitch.tv/", "https://kick.com/gnlcaster"]
)
def test_a_link_off_twitch_or_youtube_is_refused(
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    as_member(monkeypatch, "1")
    resp = client.post(
        f"/series/{seeded['series_open_id']}/casts",
        json={"channel_url": url},
        headers=SESSION,
    )
    assert resp.status_code == 422, resp.text


def test_a_guest_cannot_claim(
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_clerk(monkeypatch, a_member=False, account={"id": "1", "username": "p1"})
    resp = client.post(
        f"/series/{seeded['series_open_id']}/casts",
        json={"channel_url": TWITCH},
        headers=SESSION,
    )
    assert resp.status_code == 403


BEFORE_CAST_TABLE = "d5e0f3a8b2c4"


def test_the_caster_names_become_cast_rows_and_back(tmp_path: Path) -> None:
    """Every spelling of a name becomes one Twitch link; a downgrade keeps the login."""
    url = fresh_database(tmp_path, "casts")
    upgrade_to(url, BEFORE_CAST_TABLE)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, name, battleTag, discordTag, discordId, race) VALUES "
                "(1, 'P1', 'P1#1', 'p1', '1', 'HU'), (2, 'P2', 'P2#2', 'p2', '2', 'HU'), "
                "(3, 'P3', 'P3#3', 'p3', '3', 'HU'), (4, 'P4', 'P4#4', 'p4', '4', 'HU')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO seasons (id, name, number_weeks, series_per_week) VALUES (1, 'S', 4, 2)"
            )
        )
        connection.execute(
            text("INSERT INTO teams (id, name) VALUES (1, 'A'), (2, 'B')")
        )
        connection.execute(
            text(
                "INSERT INTO matches (id, team1_id, team2_id, season_id, playday) VALUES (1, 1, 2, 1, 1)"
            )
        )
        for series_id, players, caster in (
            (1, "1, 2", " BarrenTV "),
            (2, "3, 4", "https://www.twitch.tv/ares1776/"),
            (3, "1, 3", "@grubby"),
            (4, "2, 4", "   "),
        ):
            connection.execute(
                text(
                    "INSERT INTO series (id, match_id, player1_id, player2_id, host_player_id, caster) "
                    f"VALUES ({series_id}, 1, {players}, 1, :caster)"
                ),
                {"caster": caster},
            )

    upgrade_to(url, "head")
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT series_id, user_id, channel_url FROM series_cast ORDER BY series_id"
            )
        ).all() == [
            (1, None, "https://www.twitch.tv/barrentv"),
            (2, None, "https://www.twitch.tv/ares1776"),
            (3, None, "https://www.twitch.tv/grubby"),
        ]

    from tests.migrate import downgrade_to

    downgrade_to(url, BEFORE_CAST_TABLE)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT id, caster FROM series ORDER BY id")
        ).all() == [
            (1, "barrentv"),
            (2, "ares1776"),
            (3, "grubby"),
            (4, None),
        ]
