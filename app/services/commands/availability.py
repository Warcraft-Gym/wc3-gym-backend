"""/availability: ask a channel who can play a round, with one button per answer.

The command posts a public card for one round. Every member who presses a
button writes their own answer through the same service the dashboard and the
captain grid use, so the three places always agree.
"""

from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING, Any

from app.core.exceptions import BadRequestError
from app.models.relationships import SeasonRoundPublic
from app.services import discord_roles
from app.services.availability import AvailabilityService
from app.services.commands.base import PRIVATE, PUBLIC, caller, options_of

if TYPE_CHECKING:
    from app.services.interactions import Services

COMMAND: dict[str, Any] = {
    "name": "availability",
    "description": "Ask who can play a round of the season",
    "options": [
        {
            "type": 4,
            "name": "week",
            "description": "The week of the season; the current round when left out",
            "required": False,
            "min_value": 1,
        }
    ],
}

# Button styles: green, red, grey
ANSWERS = (("yes", "Can play", 3), ("no", "Cannot play", 4), ("clear", "Clear", 2))
VALUES = {"yes": True, "no": False, "clear": None}
SAVED = {
    "yes": "Saved: you can play week {n}.",
    "no": "Saved: you cannot play week {n}.",
    "clear": "Saved: your answer for week {n} is cleared.",
}


def _stamp(day: date) -> str:
    return f"<t:{int(datetime.combine(day, time.min, UTC).timestamp())}:D>"


def _window(round_: SeasonRoundPublic) -> str:
    if not round_.start_date:
        return ""
    if not round_.end_date or round_.end_date == round_.start_date:
        return f" · {_stamp(round_.start_date)}"
    return f" · {_stamp(round_.start_date)} to {_stamp(round_.end_date)}"


def _current(rounds: list[SeasonRoundPublic]) -> SeasonRoundPublic | None:
    """The first round that has not ended; the last one when all have."""
    today = datetime.now(UTC).date()
    for round_ in rounds:
        if (round_.end_date or round_.start_date or today) >= today:
            return round_
    return rounds[-1] if rounds else None


def run(payload: dict[str, Any], services: "Services") -> tuple[dict[str, Any], bool]:
    """/availability [week]: one public card with the three answer buttons."""
    season_id = discord_roles.current_season()
    if season_id is None:
        return {"content": "No current season."}, PRIVATE
    rounds = services.seasons.get(season_id).rounds
    week = options_of(payload).get("week")
    round_ = (
        next((r for r in rounds if r.playday == week), None)
        if week
        else _current(rounds)
    )
    if round_ is None:
        return {"content": f"The season has no week {week}."}, PRIVATE
    return {
        "content": f"**Week {round_.playday}**{_window(round_)} — can you play?",
        "components": [
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": style,
                        "label": label,
                        "custom_id": f"availability:{season_id}:{round_.playday}:{answer}",
                    }
                    for answer, label, style in ANSWERS
                ],
            }
        ],
    }, PUBLIC


def press(payload: dict[str, Any], services: "Services") -> tuple[dict[str, Any], bool]:
    """A button press writes the presser's own answer and confirms it privately."""
    _, season_id, playday, answer = payload["data"]["custom_id"].split(":")
    discord_id, _ = caller(payload)
    found = services.users.find_by_discord_id(discord_id)
    if not found:
        return {
            "content": "Your Discord account is not linked to a player yet. "
            "Sign in on the site once, then press again."
        }, PRIVATE
    user_id = found[0].id
    try:
        AvailabilityService().set(
            user_id, int(season_id), int(playday), VALUES[answer], user_id
        )
    except BadRequestError as error:
        return {"content": str(error)}, PRIVATE
    return {"content": SAVED[answer].format(n=playday)}, PRIVATE
