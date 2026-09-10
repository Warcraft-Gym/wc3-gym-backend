"""/stats: one player's GNL season, from the stored ladder and his series.

The ladder numbers are the season's window only, never the whole w3champions
season: the league scores a player on the race he registered on, so that
race's record and MMR lead, and the other races he laddered in the window
follow as off-races.
"""

import os
from typing import Any
from urllib.parse import quote

from app.core.exceptions import NotFoundError
from app.core.query import QueryUtil
from app.models.series import SeriesPublic
from app.models.user import UserPublic
from app.models.w3c_ladder_match import LadderPlayer
from app.services import discord, discord_roles
from app.services.commands.base import (
    PUBLIC,
    Services,
    options_of,
    season_span,
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
    "description": "A player's GNL season: series, ladder record, points and badges",
    "options": [PLAYER_OPTION],
}


# The UK nations Discord draws as flags; Northern Ireland has no emoji
NATION_FLAGS = ("GB-ENG", "GB-SCT", "GB-WLS")


def _flag(country: str | None) -> str:
    """The flag emoji of a country code, or nothing: regional indicators for
    a two-letter code, a tag sequence for a UK nation."""
    code = (country or "").upper()
    if len(code) == 2 and code.isalpha():
        return "".join(chr(0x1F1E6 + ord(letter) - ord("A")) for letter in code)
    if code in NATION_FLAGS:
        tags = "".join(
            chr(0xE0000 + ord(letter)) for letter in code.replace("-", "").lower()
        )
        return f"\U0001f3f4{tags}\U000e007f"
    return ""


def _icon(name: str | None, emojis: dict[str, str]) -> str:
    """The app emoji of a race, the GNL mark or the crown before a text, or
    nothing until `just discord-emojis` has uploaded it."""
    return f"<:{name}:{emojis[name]}> " if name in emojis else ""


def _record(race: str, wins: int, losses: int, emojis: dict[str, str]) -> str:
    return f"{_icon(race, emojis)}{race} {wins}-{losses}"


def _header(user: UserPublic, answer: LadderPlayer, emojis: dict[str, str]) -> str:
    """Race, flag and name, then the links to his GNL page and his
    w3champions profile."""
    line = (
        f"{_icon(answer.race, emojis)}{_flag(user.country)} **{answer.name}**".strip()
    )
    site = (os.getenv("FRONTEND_URL") or "").rstrip("/")
    if site:
        key = quote(user.battleTag, safe="") if user.battleTag else user.id
        line += f" · {_icon('gnl', emojis)}[GNL profile]({site}/player/{key})"
    if user.battleTag:
        profile = f"https://www.w3champions.com/player/{quote(user.battleTag, safe='')}"
        line += f" · {_icon('w3champions', emojis)}[w3champions ↗]({profile})"
    return line


def _series_lines(series: list[SeriesPublic], user_id: int) -> tuple[str, list[str]]:
    """The player's series record and one line per series, from his side:
    the score of a played one, the time of a scheduled one, else TBD."""
    wins = losses = 0
    lines = []
    for one in series:
        mine = one.player1_id == user_id
        other = one.player2 if mine else one.player1
        match = one.match
        team = (match.team2 if mine else match.team1) if match else None
        name = (other.name if other else None) or "?"
        line = f"Wk {match.playday if match else '?'} · vs "
        line += f"{name} ({team.name})" if team else name
        own, theirs = (
            (one.player1_score, one.player2_score)
            if mine
            else (one.player2_score, one.player1_score)
        )
        if own is not None and theirs is not None:
            won = own > theirs
            wins += won
            losses += not won
            line += f" · {own}-{theirs} {'W' if won else 'L'}"
        elif one.date_time:
            line += f" · <t:{int(one.date_time.timestamp())}:f>"
        else:
            line += " · TBD"
        lines.append(line)
    return f"{wins}-{losses}", lines


def stats(payload: dict[str, Any], services: Services) -> tuple[dict[str, Any], bool]:
    """/stats player: the season's range, his series, and his ladder grind in
    it: points, badges, the record and MMR on his race, the off-races, the
    record by opponent race, and when the ladder was last synced."""
    season_id = discord_roles.current_season()
    if season_id is None:
        return {"content": "No current season."}, PUBLIC
    user_id = int(options_of(payload)["player"])
    try:
        answer = services.ladder.user_ladder(user_id, season_id)
    except NotFoundError:
        return {"content": "No player with that id."}, PUBLIC
    user = services.users.get(user_id)
    season = services.seasons.get(season_id)
    off_races = services.ladder.off_race_records(user_id, season_id)
    query = f"player1_id == {user_id} or player2_id == {user_id}"
    series = services.series.search_for_season(
        season_id, QueryUtil.parse_query(query), sort="date_time"
    )
    if not answer.games and not off_races and not series:
        return {"content": f"No ladder games synced for {answer.name}."}, PUBLIC
    emojis = discord.app_emojis(payload["application_id"])

    record, series_lines = _series_lines(series, user_id)
    grind = [
        f"{answer.ladder_points} ladder points",
        (
            f"{answer.points - answer.ladder_points} achievement points · "
            f"{len(answer.achievements)} badges"
        ),
    ]
    if answer.race:
        line = _record(answer.race, answer.wins, answer.losses, emojis)
        if answer.mmr.current is not None:
            line += f" · {answer.mmr.current} MMR"
        grind.append(line)
    if off_races:
        grind.append(
            "Off-race "
            + " · ".join(
                _record(race, wins, losses, emojis)
                for race, (wins, losses) in off_races.items()
            )
        )
    versus = " · ".join(
        _record(race, wins, losses, emojis)
        for race, (wins, losses) in answer.vs_race.items()
        if wins + losses
    )
    if versus:
        grind.append(f"vs {versus}")
    if answer.synced_at:
        grind.append(f"Synced <t:{int(answer.synced_at.timestamp())}:R>")
    else:
        grind.append("Sync incomplete")
    fields = []
    if series_lines:
        fields.append(
            {"name": f"GNL Series · {record}", "value": "\n".join(series_lines)}
        )
    fields.append({"name": "Ladder Grind", "value": "\n".join(grind)})
    return {
        "embeds": [
            {
                "description": (
                    f"{_header(user, answer, emojis)}\n{season.name} · {season_span(season)}"
                ),
                "fields": fields,
                "color": 0x4A4DB8,
            }
        ]
    }, PUBLIC


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
