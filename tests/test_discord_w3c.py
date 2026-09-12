"""/stats reads the stored ladder and the player's series, never w3champions."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.base import ident
from app.models.enums import Race
from app.models.user import User
from app.services import discord
from app.services.ladder import LadderService
from tests.discord import CHANNEL, autocomplete, command, signed
from tests.test_ladder_read import INSIDE, add_match, sign_up, stamp_ladder

SYNCED = datetime(2026, 1, 20, 8, 0, tzinfo=UTC)


def _ladder(seeded: dict[str, Any]) -> int:
    """P1 signs up on Human and plays three rated games on it, two wins and a
    loss, plus one Orc game the league does not score."""
    player = seeded["player_ids"][0]
    sign_up(seeded["season_id"], [player])
    add_match(player, "w1", won=True, mmr_before=1500, mmr_after=1512)
    add_match(
        player,
        "w2",
        won=True,
        start_time=INSIDE + timedelta(minutes=20),
        mmr_before=1512,
        mmr_after=1524,
    )
    add_match(
        player,
        "l1",
        won=False,
        opp_race=Race.NE,
        start_time=INSIDE + timedelta(minutes=40),
        mmr_before=1524,
        mmr_after=1512,
    )
    add_match(
        player,
        "oc1",
        won=False,
        race=Race.OC,
        start_time=INSIDE + timedelta(minutes=60),
        mmr_before=1300,
        mmr_after=1290,
    )
    return player


@pytest.fixture(autouse=True)
def emojis(monkeypatch: pytest.MonkeyPatch) -> None:
    """The app has the HU icon, the GNL mark and the crown uploaded, OC and NE
    not yet."""
    monkeypatch.setenv("FRONTEND_URL", "https://gnl.example/")
    monkeypatch.setattr(
        discord,
        "app_emojis",
        lambda _: {"HU": "11", "gnl": "22", "w3champions": "33"},
    )


def _post(client: Client, payload: dict[str, Any]) -> None:
    body, headers = signed(payload)
    assert client.post("/discord/interactions", content=body, headers=headers).json()


def test_stats_posts_the_gnl_season_as_an_embed(
    client: Client, public_key: None, discord_calls: list, seeded: dict[str, Any]
) -> None:
    player = _ladder(seeded)
    stamp_ladder(player, 25, SYNCED)
    _post(client, command("stats", player=player))
    (post, delete) = discord_calls
    assert post[:2] == ("POST", CHANNEL)
    embed = post[2]["embeds"][0]
    header, season = embed["description"].splitlines()
    assert header == (
        "<:HU:11> 🇩🇪 **P1**"
        " · <:gnl:22> [GNL profile](https://gnl.example/player/P1%231111)"
        " · <:w3champions:33> [w3champions ↗](https://www.w3champions.com/player/P1%231111)"
    )
    assert season == "Season 1 · 2026-01-05 to 2026-02-27 · ended"
    # The seed plays P1 against P3 of Beta on playday 1, 2-1 to P1
    assert embed["fields"][0] == {
        "name": "GNL Series · 1-0",
        "value": "Round 1 · vs P3 (Beta) · 2-1 W",
    }
    # 3 a win and 1 a loss make the ladder points; the badges pay the rest.
    # The Orc game counts as an off-race, not in the record or the points.
    assert embed["fields"][1] == {
        "name": "Ladder Grind",
        "value": "\n".join(
            [
                "7 ladder points",
                "6 achievement points · 2 badges",
                "<:HU:11> HU 2-1 · 1512 MMR",
                "Off-race OC 0-1",
                "vs <:HU:11> HU 2-0 · NE 0-1",
                f"Synced <t:{int(SYNCED.timestamp())}:R>",
            ]
        ),
    }
    assert "title" not in embed and "footer" not in embed
    assert delete[0] == "DELETE"


def test_stats_before_any_game_shows_the_series_and_an_empty_grind(
    client: Client, public_key: None, discord_calls: list, seeded: dict[str, Any]
) -> None:
    player = seeded["player_ids"][0]
    sign_up(seeded["season_id"], [player])
    _post(client, command("stats", player=player))
    embed = discord_calls[0][2]["embeds"][0]
    assert embed["fields"][0]["name"] == "GNL Series · 1-0"
    assert embed["fields"][1]["value"].splitlines() == [
        "0 ladder points",
        "0 achievement points · 0 badges",
        "<:HU:11> HU 0-0",
        "Sync incomplete",
    ]


def test_stats_says_when_nothing_is_synced(
    client: Client, public_key: None, discord_calls: list, seeded: dict[str, Any]
) -> None:
    # A player with no series and no games
    with Session() as session:
        user = User(
            name="P9", battleTag="P9#9999", discordTag="p9", discordId="9", race=Race.UD
        )
        session.add(user)
        session.commit()
        player = ident(user)
    sign_up(seeded["season_id"], [player])
    _post(client, command("stats", player=player))
    assert discord_calls[0][2] == {"content": "No ladder games synced for P9."}
    _post(client, command("stats", player=9999))
    assert discord_calls[2][2] == {"content": "No player with that id."}


def test_player_autocomplete_lists_the_seasons_players(
    client: Client,
    public_key: None,
    seeded: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discord fires one interaction per keystroke inside a 2 s wall, so the
    choices read the roster alone, never the draft page's aggregation."""

    def refuse(self: LadderService, season_id: int) -> list:
        raise AssertionError("the autocomplete must not read the ladder aggregation")

    monkeypatch.setattr(LadderService, "season_players", refuse)
    first, second = seeded["player_ids"][:2]
    sign_up(seeded["season_id"], [first, second])
    body, headers = signed(autocomplete("stats", "1", ""))
    assert client.post(
        "/discord/interactions", content=body, headers=headers
    ).json() == {
        "type": 8,
        "data": {
            "choices": [
                {"name": "P1 (Alpha)", "value": first},
                {"name": "P2 (Alpha)", "value": second},
            ]
        },
    }
    body, headers = signed(autocomplete("stats", "1", "p2"))
    assert client.post(
        "/discord/interactions", content=body, headers=headers
    ).json() == {
        "type": 8,
        "data": {"choices": [{"name": "P2 (Alpha)", "value": second}]},
    }


def test_a_flag_is_drawn_for_a_country_or_a_uk_nation() -> None:
    from app.services.commands.base import flag

    assert flag("DE") == "🇩🇪"
    assert flag("de") == "🇩🇪"
    assert flag("GB-SCT") == "🏴󠁧󠁢󠁳󠁣󠁴󠁿"
    assert flag("GB-NIR") == ""
    assert flag(None) == ""
