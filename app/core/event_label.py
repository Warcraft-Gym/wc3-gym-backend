"""The one way an event is named where its league matters: "GNL · Season 18".

Every Discord card and command that prints an event name calls label(), so the
league shows in one place rather than in each card's own f-string.
"""


def label(name: str | None, league_short_name: str | None) -> str:
    """The league's short name, a middle dot, then the event name.

    The name alone when the event has no league, or when the name already
    opens with the short name.
    """
    text = name or "?"
    if not league_short_name or text.startswith(league_short_name):
        return text
    return f"{league_short_name} · {text}"
