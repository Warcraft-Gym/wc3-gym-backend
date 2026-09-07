"""/stats: the one command that reads the stored w3champions ladder.

It reads what the daily sync wrote, never w3champions itself. The league
scores a player on the race he registered on, so the season numbers cover that
one race; the MMR and record of every race he plays come from his stored
w3champions rows, the signup race first and in bold.
"""

from typing import Any
from urllib.parse import quote

from app.core.exceptions import NotFoundError
from app.models.user import UserPublic
from app.models.w3c_ladder_match import UserLadder
from app.models.w3c_stats import W3CStatsPublic
from app.services import discord, discord_roles
from app.services.interactions import (
    PUBLIC,
    Services,
    _season_span,
    _snapshot,
    options_of,
    typed_option,
)

# The player option; its value is the GNL user id
PLAYER_OPTION = {
    "type": 4,
    "name": "player",
    "description": "A player of the current season",
    "required": True,
    "autocomplete": True,
}

STATS: dict[str, Any] = {
    "name": "stats",
    "description": "A player's season record, and his MMR and record on every race",
    "options": [PLAYER_OPTION],
}


def _record(
    payload: dict[str, Any], services: Services
) -> tuple[int, UserLadder, UserPublic, list[W3CStatsPublic]] | dict[str, Any]:
    """The current season, the player's record of it, the player and his
    newest w3champions rows, or the answer to send instead."""
    season_id = discord_roles.current_season()
    if season_id is None:
        return {"content": "No current season."}
    user_id = int(options_of(payload)["player"])
    try:
        answer = services.ladder.user_ladder(user_id, season_id, limit=1)
    except NotFoundError:
        return {"content": "No player with that id."}
    user = services.users.get(user_id)
    rows = _newest_per_race(user.w3c_stats, answer.race)
    if not answer.games and not rows:
        return {"content": f"No ladder games synced for {answer.name}."}
    return season_id, answer, user, rows


def _flag(country: str | None) -> str:
    """The flag emoji of a two-letter country code, or nothing."""
    if not country or len(country) != 2 or not country.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(letter) - ord("A")) for letter in country.upper())


def _newest_per_race(
    rows: list[W3CStatsPublic], signup_race: str | None
) -> list[W3CStatsPublic]:
    """The newest w3champions row of every race he has games on: the signup
    race first, then the rest by MMR."""
    newest: dict[str | None, W3CStatsPublic] = {}
    for row in rows:
        if row.games and (
            row.race not in newest or row.wc3_season > newest[row.race].wc3_season
        ):
            newest[row.race] = row
    return sorted(
        newest.values(), key=lambda row: (row.race != signup_race, -(row.mmr or 0))
    )


def _icon(name: str | None, emojis: dict[str, str]) -> str:
    """The app emoji of a race or the crown before a text, or nothing until
    `just discord-emojis` has uploaded it."""
    return f"<:{name}:{emojis[name]}> " if name in emojis else ""


def _race_lines(
    rows: list[W3CStatsPublic], signup_race: str | None, emojis: dict[str, str]
) -> list[str]:
    """One line per race, the signup race in bold; a row from an older
    w3champions season than his newest names it. No row on the signup race
    says so, so a player yet to play it still shows his other races."""
    newest = max((row.wc3_season for row in rows), default=0)
    lines = []
    for row in rows:
        mmr = f"{row.mmr} MMR" if row.mmr is not None else "no MMR yet"
        text = f"{row.race} {mmr} · {row.wins or 0}-{row.losses or 0}"
        if row.wc3_season < newest:
            text += f" (S{row.wc3_season})"
        text = f"**{text}**" if row.race == signup_race else text
        lines.append(_icon(row.race, emojis) + text)
    if signup_race and all(row.race != signup_race for row in rows):
        lines.insert(0, f"{_icon(signup_race, emojis)}**{signup_race} no games yet**")
    return lines


def stats(payload: dict[str, Any], services: Services) -> tuple[dict[str, Any], bool]:
    """/stats player: the season's range, the player's record and points in it
    and by opponent race, and his MMR and record on every race for the whole
    w3champions season."""
    found = _record(payload, services)
    if isinstance(found, dict):
        return found, PUBLIC
    season_id, answer, user, rows = found
    season = services.seasons.get(season_id)
    emojis = discord.app_emojis(payload["application_id"])
    versus = " · ".join(
        f"{_icon(race, emojis)}{race} {wins}-{losses}"
        for race, (wins, losses) in answer.vs_race.items()
        if wins + losses
    )
    newest = max((row.wc3_season for row in rows), default=None)
    fields = []
    if versus:
        fields.append({"name": "GNL record by opponent race", "value": versus})
    fields.append(
        {
            "name": f"w3champions S{newest} · all games, not just GNL"
            if newest
            else "w3champions",
            "value": "\n".join(_race_lines(rows, answer.race, emojis)),
        }
    )
    embed = {
        "title": f"{_flag(user.country)} {answer.name} · {season.name}".strip(),
        "description": (
            f"{_season_span(season)}\n"
            f"{answer.wins}-{answer.losses} · {answer.games} games\n"
            f"{answer.ladder_points} ladder points · "
            f"{answer.points - answer.ladder_points} achievement points · "
            f"{len(answer.achievements)} badges"
        ),
        "fields": fields,
        "color": 0x4A4DB8,
        **_snapshot(
            "Ladder synced" if answer.synced_at else "Ladder sync incomplete as of",
            answer.synced_at,
        ),
    }
    if user.battleTag:
        embed["author"] = {
            "name": "w3champions profile",
            "url": f"https://www.w3champions.com/player/{quote(user.battleTag, safe='')}",
        }
        if "w3champions" in emojis:
            embed["author"]["icon_url"] = discord.emoji_url(emojis["w3champions"])
    return {"embeds": [embed]}, PUBLIC


def player_choices(payload: dict[str, Any], services: Services) -> list[dict[str, Any]]:
    """The autocomplete choices for a `player` option: this season's players."""
    season_id = discord_roles.current_season()
    if season_id is None:
        return []
    typed = typed_option(payload)
    names = (
        (f"{row.name} ({row.team})" if row.team else str(row.name), row.id)
        for row in services.ladder.season_players(season_id)
    )
    return [
        {"name": name[:100], "value": user_id}
        for name, user_id in names
        if typed in name.lower()
    ][:25]
