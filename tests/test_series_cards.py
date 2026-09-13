"""The series cards: the player line and its MMR, the veto by the season's map
rules, the round's dates, the W3C footer, and how /upcoming orders and fits.
The seeded open series is P2 (US, side A) against P4 (SE, side B)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx2 import Client
from sqlmodel import select

from app.core.db import Session
from app.models.enums import Race
from app.models.relationships import round_row
from app.models.season import Season
from app.models.series import Series
from app.models.series_cast import SeriesCast
from app.models.types import utcnow
from app.models.user import User
from app.models.w3c_ladder_match import W3CLadderMatch
from app.services import discord, series_cards
from app.services.series import SeriesService
from tests.seed import add_bets
from tests.test_series_veto import pool, taken  # noqa: F401  # pool is a fixture

SITE = "https://gnl.test"


def test_a_player_reads_flag_name_race_and_mmr(
    seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FRONTEND_URL", SITE)
    monkeypatch.setattr(discord, "app_emojis", lambda _: {"race_oc": "7"})
    series = SeriesService().get(seeded["series_open_id"])
    assert series.player1 and series.player2
    marks = series_cards.Ratings({(series.player1.id, Race.OC): 1500}, None)
    assert series_cards.player(series.player1, "OC", marks) == (
        f"🇺🇸 **[P2](<{SITE}/player/P2%232222>)** (<:race_oc:7> 1500)"
    )
    # No MMR on that race and no uploaded icon: the race's code and a question mark
    assert series_cards.player(series.player2, "UD", marks) == (
        f"🇸🇪 **[P4](<{SITE}/player/P4%234444>)** (UD ?)"
    )


def test_ratings_take_the_latest_synced_mmr_on_each_race(
    seeded: dict[str, Any],
) -> None:
    """Whatever the season: the card shows the last number the sync stored."""
    p2 = seeded["player_ids"][1]
    now = utcnow()
    with Session.begin() as session:
        for number, (days, mmr) in enumerate(((30, 1400), (1, 1450))):
            session.add(
                W3CLadderMatch(
                    w3c_match_id=f"m{number}",
                    wc3_season=25,
                    start_time=now - timedelta(days=days),
                    duration_s=900,
                    race=Race.OC,
                    won=True,
                    mmr_before=mmr - 20,
                    mmr_after=mmr,
                    user_id=p2,
                )
            )
    marks = series_cards.ratings([SeriesService().get(seeded["series_open_id"])])
    assert marks.mmr == {(p2, Race.OC): 1450}


def test_veto_rules_name_each_game_and_the_left_over_map(
    client: Client,
    seeded: dict[str, Any],
    pool: list[int],  # noqa: F811  # the fixture of the veto tests
    member: Callable[..., dict[str, str]],
) -> None:
    """With veto rules each pick is its game, in order, and the map nobody
    banned or picked plays last. There is no loser, so no picks line."""
    with Session.begin() as session:
        season = session.get(Season, seeded["season_id"])
        assert season
        season.map_rules = "veto,veto,veto"
    series_id = seeded["series_open_id"]
    side_a, side_b = member("2"), member("4")
    taken(client, series_id, side_a, pool[1])
    taken(client, series_id, side_b, pool[2])
    taken(client, series_id, side_a, pool[3])
    taken(client, series_id, side_b, pool[4])
    assert series_cards.veto_lines(SeriesService().get(series_id)) == [
        "Game 1 · LR, P2's pick",
        "Game 2 · AL, P4's pick",
        "Game 3 · Concealed Hill, left over",
    ]


def test_a_one_day_round_shows_one_date(seeded: dict[str, Any]) -> None:
    with Session.begin() as session:
        row = round_row(session, seeded["season_id"], 1)
        assert row
        row.end_date = row.start_date
    noon = int(datetime(2026, 1, 5, 12, tzinfo=UTC).timestamp())
    assert series_cards.round_line(seeded["season_id"], 1) == f"Round 1: <t:{noon}:d>"


def test_the_footer_carries_the_w3c_logo_and_the_oldest_sync(
    seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The time is the embed's timestamp, so Discord keeps it true for days."""
    monkeypatch.setattr(discord, "app_emojis", lambda _: {"w3c": "9"})
    oldest = datetime(2026, 9, 9, 12, 39, tzinfo=UTC)
    # P2 synced an hour after P4: the card shows P4's, the older of its two players
    p2, p4 = seeded["player_ids"][1], seeded["player_ids"][3]
    with Session.begin() as session:
        for user_id, hours in ((p2, 1), (p4, 0)):
            user = session.get(User, user_id)
            assert user
            user.ladder_synced_at = oldest + timedelta(hours=hours)
    card = series_cards.claim_card(SeriesService().get(seeded["series_open_id"]))
    embed = card["embeds"][0]
    assert embed["footer"] == {
        "text": "MMR synced",
        "icon_url": "https://cdn.discordapp.com/emojis/9.png",
    }
    assert datetime.fromisoformat(embed["timestamp"]) == oldest


def _open_series(seeded: dict[str, Any]) -> list[Any]:
    """Every series of the seeded season, the played one a day out, the open
    one two days out and claimed."""
    first, later = utcnow() + timedelta(days=1), utcnow() + timedelta(days=2)
    with Session.begin() as session:
        played = session.get(Series, seeded["series_played_id"])
        claimed = session.get(Series, seeded["series_open_id"])
        assert played and claimed
        played.date_time, claimed.date_time = first, later
        claimed.casts.append(SeriesCast(channel_url="https://twitch.tv/gnlcaster"))
    with Session() as session:
        ids = session.scalars(select(Series.id)).all()
    return [SeriesService().get(series_id) for series_id in ids]


def test_upcoming_gives_each_round_its_embed(seeded: dict[str, Any]) -> None:
    with Session() as session:
        add_bets(session, seeded, 1)  # a match on playday 2 with a series of its own
        session.commit()
    embeds = series_cards.upcoming(_open_series(seeded), lambda _: False)["embeds"]
    assert [embed["description"].splitlines()[1][:7] for embed in embeds] == [
        "Round 1",
        "Round 2",
    ]
    # The footer closes the reply once, on its last embed
    assert "footer" not in embeds[0] and "footer" in embeds[-1]


def test_upcoming_counts_what_does_not_fit(
    seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    monkeypatch.setattr(series_cards, "BUDGET", 100)
    rows = _open_series(seeded)
    description = series_cards.upcoming(rows, lambda _: False)["embeds"][-1][
        "description"
    ]
    assert description.endswith(f"And {len(rows)} more series")
