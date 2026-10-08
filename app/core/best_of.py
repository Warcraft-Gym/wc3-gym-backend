"""The best-of of each part of an elimination bracket.

A stage plays its own best_of in every round, unless its best_of_by_round
names a role of the bracket, counted back from the end, with a best-of of its
own: "semifinal:3,final:5". The field size is not known before the draw, so a
role names a part of the bracket and never a round number. The bracket plan
names the role of each round it writes, and the round row keeps the best-of.
"""

# Single elimination counts back from the final; double elimination names the
# finals of both ladders, the round before each, and the grand final, whose
# reset plays like it
ROLES = (
    "quarterfinal",
    "semifinal",
    "final",
    "upper_semifinal",
    "upper_final",
    "lower_semifinal",
    "lower_final",
    "grand_final",
)


def parse_plan(text: str | None) -> dict[str, int]:
    """The best-of of every role the stage names, as "semifinal:3,final:5" reads."""
    plan: dict[str, int] = {}
    for token in (text or "").split(","):
        if ":" not in token:
            continue
        role, _, best_of = token.partition(":")
        if role.strip() in ROLES and best_of.strip().isdigit():
            plan[role.strip()] = int(best_of)
    return plan


def largest_best_of(best_of: int, text: str | None) -> int:
    """The most games one series of the stage can play: what its map pool must hold."""
    return max([best_of, *parse_plan(text).values()])
