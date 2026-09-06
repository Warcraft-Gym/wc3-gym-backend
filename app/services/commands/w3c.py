"""The two commands that read the stored w3champions ladder: /mmr and /stats.

Both read what the daily sync wrote, never w3champions itself. The league
scores a player on the race he registered on, so a season answer covers that
one race and no other.
"""

from typing import Any

from app.core.exceptions import NotFoundError
from app.models.enums import Race
from app.models.w3c_ladder_match import UserLadder
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
    "description": "What a player's MMR is this season",
    "options": [
        PLAYER_OPTION,
        {
            "type": 3,
            "name": "race",
            "description": "The race he plays this season unless given",
            "choices": [{"name": race.value, "value": race.value} for race in Race],
        },
    ],
}

STATS: dict[str, Any] = {
    "name": "stats",
    "description": "A player's ladder record this season",
    "options": [PLAYER_OPTION],
}


def _record(
    payload: dict[str, Any], services: Services
) -> tuple[int, UserLadder] | dict[str, Any]:
    """The current season and the player's record of it, or the answer to
    send instead."""
    season_id = discord_roles.current_season()
    if season_id is None:
        return {"content": "No current season."}
    try:
        answer = services.ladder.user_ladder(
            int(options_of(payload)["player"]), season_id, limit=1
        )
    except NotFoundError:
        return {"content": "No player with that id."}
    return season_id, answer


def _mmr_text(answer: UserLadder) -> str:
    """A placement run is rated by nobody, so a player in one has no MMR yet."""
    return str(answer.mmr.current) if answer.mmr.current is not None else "no MMR yet"


def mmr(payload: dict[str, Any], services: Services) -> tuple[dict[str, Any], bool]:
    """/mmr player race: the player's MMR on the race he plays this season."""
    found = _record(payload, services)
    if isinstance(found, dict):
        return found, PUBLIC
    _, answer = found
    if not answer.games:
        return {"content": f"No ladder games synced for {answer.name}."}, PUBLIC
    race = options_of(payload).get("race")
    if race and race != answer.race:
        return {"content": f"{answer.name} plays {answer.race} this season."}, PUBLIC
    return {"content": f"{answer.name} · {answer.race} · {_mmr_text(answer)}"}, PUBLIC


def stats(payload: dict[str, Any], services: Services) -> tuple[dict[str, Any], bool]:
    """/stats player: the player's season record, points, MMR and opponents."""
    found = _record(payload, services)
    if isinstance(found, dict):
        return found, PUBLIC
    season_id, answer = found
    if not answer.games:
        return {"content": f"No ladder games synced for {answer.name}."}, PUBLIC
    season = services.seasons.get(season_id)
    versus = " · ".join(
        f"{race} {wins}-{losses}"
        for race, (wins, losses) in answer.vs_race.items()
        if wins + losses
    )
    fields = [{"name": "MMR", "value": f"{answer.race} · {_mmr_text(answer)}"}]
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
