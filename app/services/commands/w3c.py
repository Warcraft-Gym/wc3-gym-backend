"""The two commands that read the stored w3champions ladder: /mmr and /stats.

Both read what the daily sync wrote, never w3champions itself. The league
scores a player on the race he registered on, so the season numbers cover that
one race; the MMR and record of every race he plays come from his stored
w3champions rows, the signup race first and in bold.
"""

from typing import Any

from app.core.exceptions import NotFoundError
from app.models.w3c_ladder_match import UserLadder
from app.models.w3c_stats import W3CStatsPublic
from app.services import discord_roles
from app.services.interactions import PUBLIC, Services, options_of, typed_option

# The player option both commands take; its value is the GNL user id
PLAYER_OPTION = {
    "type": 4,
    "name": "player",
    "description": "A player of the current season",
    "required": True,
    "autocomplete": True,
}

MMR: dict[str, Any] = {
    "name": "mmr",
    "description": "A player's MMR on every race, the one he plays this season first",
    "options": [PLAYER_OPTION],
}

STATS: dict[str, Any] = {
    "name": "stats",
    "description": "A player's ladder record this season",
    "options": [PLAYER_OPTION],
}


def _record(
    payload: dict[str, Any], services: Services
) -> tuple[int, UserLadder, list[W3CStatsPublic]] | dict[str, Any]:
    """The current season, the player's record of it and his w3champions rows,
    or the answer to send instead."""
    season_id = discord_roles.current_season()
    if season_id is None:
        return {"content": "No current season."}
    user_id = int(options_of(payload)["player"])
    try:
        answer = services.ladder.user_ladder(user_id, season_id, limit=1)
    except NotFoundError:
        return {"content": "No player with that id."}
    rows = _newest_per_race(services.users.get(user_id).w3c_stats, answer.race)
    if not answer.games and not rows:
        return {"content": f"No ladder games synced for {answer.name}."}
    return season_id, answer, rows


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


def _race_lines(
    rows: list[W3CStatsPublic], signup_race: str | None, record: bool
) -> list[str]:
    """One line per race, the signup race in bold; a row from an older
    w3champions season than his newest names it. No row on the signup race
    says so, so a player yet to play it still shows his other races."""
    newest = max((row.wc3_season for row in rows), default=0)
    lines = []
    for row in rows:
        text = f"{row.race} {row.mmr if row.mmr is not None else 'no MMR yet'}"
        if record:
            text += f" · {row.wins or 0}-{row.losses or 0}"
        if row.wc3_season < newest:
            text += f" (S{row.wc3_season})"
        lines.append(f"**{text}**" if row.race == signup_race else text)
    if signup_race and all(row.race != signup_race for row in rows):
        lines.insert(0, f"**{signup_race} no games yet**")
    return lines


def mmr(payload: dict[str, Any], services: Services) -> tuple[dict[str, Any], bool]:
    """/mmr player: the player's MMR on every race, the season's race first."""
    found = _record(payload, services)
    if isinstance(found, dict):
        return found, PUBLIC
    _, answer, rows = found
    lines = _race_lines(rows, answer.race, record=False)
    return {"content": " · ".join([str(answer.name), *lines])}, PUBLIC


def stats(payload: dict[str, Any], services: Services) -> tuple[dict[str, Any], bool]:
    """/stats player: the season record and points, every race's MMR and
    record, and the opponent races."""
    found = _record(payload, services)
    if isinstance(found, dict):
        return found, PUBLIC
    season_id, answer, rows = found
    season = services.seasons.get(season_id)
    versus = " · ".join(
        f"{race} {wins}-{losses}"
        for race, (wins, losses) in answer.vs_race.items()
        if wins + losses
    )
    newest = max((row.wc3_season for row in rows), default=None)
    fields = [
        {
            "name": f"w3champions S{newest}" if newest else "w3champions",
            "value": "\n".join(_race_lines(rows, answer.race, record=True)),
        }
    ]
    if versus:
        fields.append({"name": "Opponent races", "value": versus})
    return {
        "embeds": [
            {
                "title": f"{answer.name} · {season.name}",
                "description": (
                    f"{answer.wins}-{answer.losses} · {answer.games} games\n"
                    f"{answer.ladder_points} ladder points · "
                    f"{answer.points - answer.ladder_points} achievement points · "
                    f"{len(answer.achievements)} badges"
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
