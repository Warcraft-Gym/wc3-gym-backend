"""The Discord card about one event, and the two buttons a member presses.

One card for every kind: the event name with its league, when it runs, how it
plays, how many are in, how to enter and the link to its page. A press writes
through the same entrant service the site writes through, so the two agree,
and the reply is private.
"""

from typing import TYPE_CHECKING, Any

from app.core.config import frontend_url
from app.core.event_label import label as event_label
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.models.enums import Race, SignupChannel, SignupPolicy, StageFormat
from app.models.event_entrant import EntrantSignup, EventEntrantPublic
from app.models.season import EventPublic, MemberEventRow
from app.models.types import utcnow
from app.services import series_cards
from app.services.commands.base import LINK_FIRST, PRIVATE, caller, md
from app.services.events import EventService

if TYPE_CHECKING:
    from app.services.interactions import Services

# The first part of each button's custom_id, which routes the press
SIGN_UP, CHECK_IN = "event_signup", "event_checkin"
# How each stage format reads on a card
FORMATS = {
    StageFormat.round_robin: "round robin",
    StageFormat.gnl: "league",
    StageFormat.single_elimination: "single elimination",
    StageFormat.double_elimination: "double elimination",
    StageFormat.swiss: "swiss",
    StageFormat.koth: "king of the hill",
    StageFormat.ffa: "free for all",
}
# Who the event takes, in the words a member reads
POLICY = {
    SignupPolicy.members: "Sign up with the Discord account linked to your profile.",
    SignupPolicy.anyone: "Anyone may sign up; the site takes a battle tag.",
}
SHUT = "Signups are closed."
GONE = "That event is gone."
PER_ROUND = "This event checks in per round. Use /availability."
# What a press answers when the caller's one action is not the button's action
NO_SIGN_UP = {
    "withdraw": "You are already signed up.",
    "check_in": "You are already signed up.",
    "checked_in": "You are already signed up.",
    "view": "This event has started.",
    "closed": "Signups are closed for this event.",
}
NO_CHECK_IN = {
    "sign_up": "Sign up for this event first.",
    "checked_in": "You are already checked in.",
    "view": "This event has started.",
    "closed": "The check-in is not open.",
}
# The two sides of the window, for a member who is in and not checked in
NOT_OPEN_YET = "The check-in is not open yet."
CHECK_IN_CLOSED = "The check-in has closed."


def _when(event: EventPublic) -> str:
    """The start time of an event that has one, else its span of days."""
    if event.starts_at:
        stamp = int(event.starts_at.timestamp())
        return f"Starts <t:{stamp}:F> · <t:{stamp}:R>"
    if event.start_date is None:
        return "No dates yet"
    span = series_cards.day(event.start_date)
    if event.end_date and event.end_date != event.start_date:
        span += f" to {series_cards.day(event.end_date)}"
    return span


def _stage_lines(event: EventPublic) -> list[str]:
    """One line per stage: its name, how it plays and its best-of."""
    return [
        " · ".join(
            part
            for part in (
                md(stage.name) if stage.name else "",
                FORMATS.get(stage.format, stage.format.value),
                f"best of {stage.best_of}",
            )
            if part
        )
        for stage in event.stages
    ]


def _entrants(event: EventPublic) -> str:
    count = event.entrant_count or 0
    line = f"{count} {'entrant' if count == 1 else 'entrants'}"
    return f"{line} of {event.entrant_cap}" if event.entrant_cap else line


def _links(event: EventPublic) -> list[str]:
    site = frontend_url()
    lines = [f"[Event page](<{site}/events/{event.id}>)"] if site else []
    if event.page_url:
        lines.append(f"[Rules](<{event.page_url}>)")
    return lines


def _buttons(event: EventPublic) -> dict[str, Any]:
    """Sign up and Check in, each greyed out while its own window is shut."""
    no_actions = event.phase in ("draft", "running", "finished")
    return {
        "type": 1,
        "components": [
            {
                "type": 2,
                "style": 3,
                "label": "Sign up",
                "custom_id": f"{SIGN_UP}:{event.id}",
                "disabled": no_actions or not event.signups_open,
            },
            {
                "type": 2,
                "style": 1,
                "label": "Check in",
                "custom_id": f"{CHECK_IN}:{event.id}",
                "disabled": no_actions
                or not (event.checkin_enabled and event.checkin_open),
            },
        ],
    }


def event_card(event: EventPublic) -> dict[str, Any]:
    """The card an admin posts about an event, with its two buttons."""
    lines = [
        f"## {md(event_label(event.name, event.league_short_name))}",
        _when(event),
        *_stage_lines(event),
        _entrants(event),
        POLICY[event.signup_policy] if event.signups_open else SHUT,
        *_links(event),
    ]
    return {
        "embeds": [
            {"description": "\n".join(lines), "color": series_cards.COLOR},
        ],
        "components": [_buttons(event)],
    }


def _row(event_id: int, user_id: int) -> MemberEventRow | None:
    """The caller's own row for the event, carrying its one action word."""
    # ponytail: one read over every published event; page it if the list grows
    return next(
        (
            row
            for row in EventService().events_for_member(user_id)
            if row.id == event_id
        ),
        None,
    )


def _line(entrant: EventEntrantPublic) -> str:
    """The player standard: {flag} {name} ({race} {mmr})."""
    marks = series_cards.Ratings(
        {(entrant.user.id, Race(entrant.race)): entrant.mmr}
        if entrant.user and entrant.race and entrant.mmr is not None
        else {},
        None,
    )
    return series_cards.player(entrant.user, entrant.race, marks)


def _sign_up(
    services: "Services", row: MemberEventRow, user_id: int, discord_id: str
) -> str:
    """Enter the presser on the race his profile carries; the site changes it."""
    user = services.users.get(user_id)
    entrant = EventService().add_entrant(
        row.id,
        EntrantSignup(
            race=Race(user.race) if user.race else Race.RANDOM,
            channel=SignupChannel.bot,
        ),
        {"sub": discord_id},
    )
    named = event_label(row.name, row.league_short_name)
    return f"Signed up for {named}: {_line(entrant)}"


def _window_text(row: MemberEventRow) -> str:
    """Which side of the check-in window a press on a shut one landed on."""
    round_ = row.next_round
    closes = (round_.end_date or round_.start_date) if round_ else row.start
    return CHECK_IN_CLOSED if closes and closes < utcnow().date() else NOT_OPEN_YET


def press(payload: dict[str, Any], services: "Services") -> tuple[dict[str, Any], bool]:
    """A press on Sign up or Check in, answered privately.

    The one action the member read computes says whether the button applies,
    so the card, the home page and the event page refuse in the same words.
    """
    prefix, event_id = payload["data"]["custom_id"].split(":")
    discord_id, _ = caller(payload)
    user_id = services.users.id_by_discord_id(discord_id)
    if user_id is None:
        return {"content": LINK_FIRST}, PRIVATE
    row = _row(int(event_id), user_id)
    if row is None:
        return {"content": GONE}, PRIVATE
    signing = prefix == SIGN_UP
    if row.action != ("sign_up" if signing else "check_in"):
        if not signing and row.action == "withdraw":
            return {"content": _window_text(row)}, PRIVATE
        refusals = NO_SIGN_UP if signing else NO_CHECK_IN
        return {"content": refusals[row.action]}, PRIVATE
    try:
        if signing:
            return {"content": _sign_up(services, row, user_id, discord_id)}, PRIVATE
        if row.checkin_shape != "event" or row.entrant_id is None:
            return {"content": PER_ROUND}, PRIVATE
        EventService().check_in(row.id, row.entrant_id, {"sub": discord_id})
    except (ApiError, BadRequestError, NotFoundError) as error:
        return {"content": str(error)}, PRIVATE
    named = event_label(row.name, row.league_short_name)
    return {"content": f"Checked in for {named}."}, PRIVATE
