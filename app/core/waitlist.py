"""How many of a cup's line are in, and who waits.

The rule the frontend draws in src/helpers/events-page.mjs, written once here.
A cup's cap is the most it takes; on a cup with divisions it is the players of
one division, and the cup opens a further division each time its line fills
one, so the line comes in a whole division at a time.
"""


def places(total: int, cap: int | None, divisions: bool) -> int:
    """How many of the `total` entrants in the line are in.

    No cap takes everyone. One field takes up to its cap. A cup with divisions
    takes its first division as it fills, and then every division its line
    fills completely; the rest of the line waits for the next one.
    """
    if cap is None or cap < 1 or total <= cap:
        return total
    if not divisions:
        return cap
    return total // cap * cap
