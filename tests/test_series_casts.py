"""A member claims a series to cast, edits and removes its own claim only.

The claim rides on the series answer as `casts`, so every series table
shows it with no second read.
"""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from app.models.series_cast import vod_url
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


def test_the_caster_pastes_and_clears_a_vod(
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    series_id = seeded["series_open_id"]
    as_member(monkeypatch, "1")
    (cast,) = client.post(
        f"/series/{series_id}/casts", json={"channel_url": TWITCH}, headers=SESSION
    ).json()
    vod = f"/series/{series_id}/casts/{cast['id']}/vod"

    # A channel is not a VOD
    resp = client.put(vod, json={"vod_url": TWITCH}, headers=SESSION)
    assert resp.status_code == 422, resp.text

    video = "https://www.twitch.tv/videos/2233445566?t=1h2m"
    resp = client.put(vod, json={"vod_url": video}, headers=SESSION)
    assert resp.status_code == 200, resp.text
    (cast,) = resp.json()
    assert cast["vod_url"] == video
    assert cast["vod_added_at"] is not None

    # Another member cannot touch it; clearing drops the URL and its time
    as_member(monkeypatch, "2")
    assert client.put(vod, json={"vod_url": None}, headers=SESSION).status_code == 403
    as_member(monkeypatch, "1")
    (cast,) = client.put(vod, json={"vod_url": None}, headers=SESSION).json()
    assert cast["vod_url"] is None
    assert cast["vod_added_at"] is None


def test_a_series_that_is_over_is_claimed_with_its_vod(
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing is left to stream, so the claim carries the video page as its channel."""
    over = seeded["series_played_id"]
    as_member(monkeypatch, "1")
    assert (
        client.post(
            f"/series/{seeded['series_open_id']}/casts",
            json={"channel_url": TWITCH},
            headers=SESSION,
        ).status_code
        == 201
    )

    resp = client.post(
        f"/series/{over}/casts", json={"channel_url": TWITCH}, headers=SESSION
    )
    assert resp.status_code == 400
    assert resp.json() == {"error": "This series is over; a VOD link is needed"}

    # A channel is not a VOD
    resp = client.post(
        f"/series/{over}/casts",
        json={"channel_url": TWITCH, "vod_url": TWITCH},
        headers=SESSION,
    )
    assert resp.status_code == 422, resp.text

    video = "https://www.twitch.tv/videos/2233445566"
    resp = client.post(
        f"/series/{over}/casts",
        json={"channel_url": video, "vod_url": video},
        headers=SESSION,
    )
    assert resp.status_code == 201, resp.text
    (cast,) = resp.json()
    assert cast["vod_url"] == video
    assert cast["vod_added_at"] is not None

    # The video page is a channel no next claim starts from
    assert client.get("/casts/last", headers=SESSION).json() == {"channel_url": TWITCH}


@pytest.mark.parametrize(
    "url",
    [
        "youtu.be/dQw4w9WgXcQ?t=42",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/live/dQw4w9WgXcQ",
        "twitch.tv/videos/2233445566",
    ],
)
def test_every_video_link_form_is_a_vod(url: str) -> None:
    assert vod_url(url).endswith(url.removeprefix("https://"))


@pytest.mark.parametrize(
    "url", ["youtube.com/@grubby", "twitch.tv/grubby", "kick.com/videos/1"]
)
def test_a_channel_is_not_a_vod(url: str) -> None:
    with pytest.raises(ValueError):
        vod_url(url)


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


BEFORE_CAST_TABLE = "e6f1a9c3d5b7"
CAST_TABLE = "a9c4e7d1f2b3"


def test_the_caster_names_become_cast_rows_and_back(tmp_path: Path) -> None:
    """Every spelling of a name becomes one Twitch link; the column goes one migration later."""
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
            (5, "3, 1", "zinithin"),
        ):
            connection.execute(
                text(
                    "INSERT INTO series (id, match_id, player1_id, player2_id, host_player_id, caster) "
                    f"VALUES ({series_id}, 1, {players}, 1, :caster)"
                ),
                {"caster": caster},
            )

    upgrade_to(url, CAST_TABLE)
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT series_id, user_id, channel_url FROM series_cast ORDER BY series_id"
            )
        ).all() == [
            (1, None, "https://www.twitch.tv/barrentv"),
            (2, None, "https://www.twitch.tv/ares1776"),
            (3, None, "https://www.twitch.tv/grubby"),
            (5, None, "https://www.twitch.tv/zinithin"),
        ]
        # The column stays until the code that read it has shipped
        assert (
            connection.execute(text("SELECT caster FROM series WHERE id = 2")).scalar()
            == "https://www.twitch.tv/ares1776/"
        )

    upgrade_to(url, "head")
    with engine.connect() as connection:
        columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(series)"))
        }
        assert "caster" not in columns
        # The name with no Twitch channel is gone with the column
        assert connection.execute(
            text("SELECT series_id FROM series_cast ORDER BY series_id")
        ).scalars().all() == [1, 2, 3]

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
            (5, None),
        ]


def test_a_youtube_stream_url_is_its_own_vod_once_the_series_is_over(
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The caster pastes nothing: the watch URL stays the same after the stream."""
    from app.core.db import Session
    from app.models.series import Series

    series_id = seeded["series_open_id"]
    stream = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    as_member(monkeypatch, "1")
    (cast,) = client.post(
        f"/series/{series_id}/casts", json={"channel_url": stream}, headers=SESSION
    ).json()
    assert cast["vod_url"] is None

    # One stream is not a channel, so it starts no next claim
    assert client.get("/casts/last", headers=SESSION).json() == {"channel_url": None}

    with Session.begin() as session:
        series = session.get(Series, series_id)
        assert series
        series.player1_score, series.player2_score = 2, 1

    (cast,) = client.get(f"/series/{series_id}/casts").json()
    assert cast["vod_url"] == stream
    # Nothing was pasted, so nothing dates the VOD
    assert cast["vod_added_at"] is None
    assert client.get(f"/series/{series_id}").json()["casts"][0]["vod_url"] == stream
