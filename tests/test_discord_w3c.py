"""/mmr and /stats: both read the stored w3champions ladder, never w3champions."""

from datetime import timedelta
from typing import Any

from httpx2 import Client

from app.models.enums import Race
from tests.discord import CHANNEL, autocomplete, command, signed
from tests.test_ladder_read import INSIDE, add_match, sign_up


def _ladder(seeded: dict[str, Any]) -> int:
    """P1 signs up on Human and plays three rated games: two wins, one loss."""
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
    return player


def _post(client: Client, payload: dict[str, Any]) -> None:
    body, headers = signed(payload)
    assert client.post("/discord/interactions", content=body, headers=headers).json()


def test_mmr_posts_one_line_publicly(
    client: Client, public_key: None, discord_calls: list, seeded: dict[str, Any]
) -> None:
    player = _ladder(seeded)
    _post(client, command("mmr", player=player))
    (post, delete) = discord_calls
    assert post[:2] == ("POST", CHANNEL)
    assert post[2] == {"content": "P1 · HU · 1512"}
    assert delete[0] == "DELETE"


def test_mmr_answers_the_race_he_plays_this_season(
    client: Client, public_key: None, discord_calls: list, seeded: dict[str, Any]
) -> None:
    player = _ladder(seeded)
    _post(client, command("mmr", player=player, race="HU"))
    assert discord_calls[0][2] == {"content": "P1 · HU · 1512"}
    _post(client, command("mmr", player=player, race="NE"))
    assert discord_calls[2][2] == {"content": "P1 plays HU this season."}


def test_mmr_says_when_nothing_is_synced(
    client: Client, public_key: None, discord_calls: list, seeded: dict[str, Any]
) -> None:
    sign_up(seeded["season_id"], [seeded["player_ids"][0]])
    _post(client, command("mmr", player=seeded["player_ids"][0]))
    assert discord_calls[0][2] == {"content": "No ladder games synced for P1."}
    _post(client, command("mmr", player=9999))
    assert discord_calls[2][2] == {"content": "No player with that id."}


def test_stats_posts_the_season_record_as_an_embed(
    client: Client, public_key: None, discord_calls: list, seeded: dict[str, Any]
) -> None:
    player = _ladder(seeded)
    _post(client, command("stats", player=player))
    (post, delete) = discord_calls
    assert post[:2] == ("POST", CHANNEL)
    embed = post[2]["embeds"][0]
    assert embed["title"] == "P1 · Season 1"
    first, second = embed["description"].splitlines()
    assert first == "2-1 · 3 games"
    # 3 a win and 1 a loss make the ladder points; the badges pay the rest
    assert second == "7 ladder points · 5 achievement points · 2 badges"
    assert embed["fields"][0] == {"name": "MMR", "value": "HU · 1512"}
    assert embed["fields"][1] == {
        "name": "Opponent races",
        "value": "HU 2-0 · NE 0-1",
    }
    assert delete[0] == "DELETE"


def test_stats_says_when_nothing_is_synced(
    client: Client, public_key: None, discord_calls: list, seeded: dict[str, Any]
) -> None:
    sign_up(seeded["season_id"], [seeded["player_ids"][0]])
    _post(client, command("stats", player=seeded["player_ids"][0]))
    assert discord_calls[0][2] == {"content": "No ladder games synced for P1."}


def test_player_autocomplete_lists_the_seasons_players(
    client: Client, public_key: None, seeded: dict[str, Any]
) -> None:
    first, second = seeded["player_ids"][:2]
    sign_up(seeded["season_id"], [first, second])
    body, headers = signed(autocomplete("mmr", "1", ""))
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
