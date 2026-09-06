"""/mmr and /stats: both read the stored w3champions ladder, never w3champions."""

from datetime import timedelta
from typing import Any

from httpx2 import Client

from app.core.db import Session
from app.models.enums import Race
from app.models.w3c_stats import W3CStats
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


def _w3c_rows(player: int, *races: Race) -> None:
    """His w3champions rows: HU and NE this season, OC last season, UD unplayed."""
    rows = {
        Race.HU: {"wc3_season": 26, "mmr": 1512, "wins": 40, "losses": 30, "games": 70},
        Race.NE: {"wc3_season": 26, "mmr": 1400, "wins": 5, "losses": 7, "games": 12},
        Race.OC: {"wc3_season": 25, "mmr": 1300, "wins": 2, "losses": 1, "games": 3},
        Race.UD: {"wc3_season": 26, "mmr": 1000, "wins": 0, "losses": 0, "games": 0},
    }
    with Session() as session:
        for race in races:
            session.add(W3CStats(user_id=player, race=race, **rows[race]))
        session.commit()


def _post(client: Client, payload: dict[str, Any]) -> None:
    body, headers = signed(payload)
    assert client.post("/discord/interactions", content=body, headers=headers).json()


def test_mmr_posts_every_race_with_the_signup_race_first(
    client: Client, public_key: None, discord_calls: list, seeded: dict[str, Any]
) -> None:
    player = _ladder(seeded)
    _w3c_rows(player, Race.NE, Race.UD, Race.OC, Race.HU)
    _post(client, command("mmr", player=player))
    (post, delete) = discord_calls
    assert post[:2] == ("POST", CHANNEL)
    # UD has no games and stays hidden; OC's row is from the older season
    assert post[2] == {"content": "P1 · **HU 1512** · NE 1400 · OC 1300 (S25)"}
    assert delete[0] == "DELETE"


def test_mmr_shows_the_other_races_before_he_plays_his_signup_race(
    client: Client, public_key: None, discord_calls: list, seeded: dict[str, Any]
) -> None:
    player = seeded["player_ids"][0]
    sign_up(seeded["season_id"], [player])
    _w3c_rows(player, Race.NE)
    _post(client, command("mmr", player=player))
    assert discord_calls[0][2] == {"content": "P1 · **HU no games yet** · NE 1400"}


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
    _w3c_rows(player, Race.HU, Race.NE, Race.OC)
    _post(client, command("stats", player=player))
    (post, delete) = discord_calls
    assert post[:2] == ("POST", CHANNEL)
    embed = post[2]["embeds"][0]
    assert embed["title"] == "P1 · Season 1"
    first, second = embed["description"].splitlines()
    assert first == "2-1 · 3 games"
    # 3 a win and 1 a loss make the ladder points; the badges pay the rest
    assert second == "7 ladder points · 6 achievement points · 2 badges"
    assert embed["fields"][0] == {
        "name": "w3champions S26",
        "value": "**HU 1512 · 40-30**\nNE 1400 · 5-7\nOC 1300 · 2-1 (S25)",
    }
    assert embed["fields"][1] == {
        "name": "Opponent races",
        "value": "HU 2-0 · NE 0-1",
    }
    assert delete[0] == "DELETE"


def test_stats_shows_the_other_races_before_he_plays_his_signup_race(
    client: Client, public_key: None, discord_calls: list, seeded: dict[str, Any]
) -> None:
    player = seeded["player_ids"][0]
    sign_up(seeded["season_id"], [player])
    _w3c_rows(player, Race.OC)
    _post(client, command("stats", player=player))
    embed = discord_calls[0][2]["embeds"][0]
    assert embed["description"].splitlines()[0] == "0-0 · 0 games"
    assert embed["fields"] == [
        {"name": "w3champions S25", "value": "**HU no games yet**\nOC 1300 · 2-1"}
    ]


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
