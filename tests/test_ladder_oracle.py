"""Our ladder numbers against the ones wc3.no publishes for GNL S18.

Run it with `W3C_ORACLE=1 uv run pytest tests/test_ladder_oracle.py -q`; it
is skipped otherwise, because it calls w3champions for real. It needs no
database: it fetches the matches, applies the scope and core.ladder, and
compares.

EXPECTED is the wc3.no GNL S18 table, read from the live page on
2026-08-27, with the race each player is registered with. Its points column
carries ladder points plus achievement points, so the comparison rebuilds
the ladder points from its own wins and losses and adds core.achievements.

The race is part of the scope, not decoration: wc3.no asks w3champions for
one race per player (`playerRace`), which matches the race the player
selected, where a random pick is Random. So a player registered RANDOM
scores his random picks alone, and a player registered on a normal race
scores no random pick that rolled it. The last four rows below are the
players only that rule explains.

The rules that read a team take the same roster wc3.no takes: it reads
`GET /teams/season/{id}` off the GNL backend, so the test does too.
"""

import os
from datetime import datetime
from typing import Any

import pytest
import requests

from app.core import achievements, ladder
from app.models.enums import Race
from app.services.w3c import W3CService

# The real function, captured before conftest blocks third party calls.
REAL_REQUEST = requests.Session.request

# GNL season 18, inclusive at both ends.
START = datetime(2026, 7, 6)
END = datetime(2026, 8, 9, 23, 59, 59, 999999)

# GNL season 18 is season 4 on the GNL backend, the id wc3.no asks for.
GNL_BACKEND = "https://backend.warcraft-gym.com"
GNL_SEASON = "4"

# battle tag, league race, wins, losses, the wc3.no points column
EXPECTED = [
    ("thanks#11187", Race.NE, 108, 117, 744),
    # 104/100, not the 103/100 the wc3.no table shows. Every offset from UTC-12 to
    # UTC+14, with the end date inside the window or outside it, was tried against
    # w3champions' own answer and none produces 103/100, while UTC with the end date
    # inside produces 104/100 exactly. His 215 matches are all Night Elf, all
    # distinct and all inside the window, and the race filter changes nothing. So
    # the extra win is one wc3.no did not see, and w3champions is the source. The
    # win is worth 3 points, so his total is expected 3 above the published 663.
    ("doctajones#11327", Race.NE, 104, 100, 663 + 3),
    ("Psike#1331", Race.UD, 60, 76, 378),
    ("ThreeWayKay#2610", Race.HU, 56, 58, 334),
    ("indrew613#1342", Race.OC, 40, 38, 250),
    ("Elusirei#2178", Race.NE, 39, 37, 209),
    ("Solanum#21803", Race.OC, 20, 6, 186),
    ("MrDrCooper#1551", Race.OC, 22, 5, 181),
    ("MIsTKy#2462", Race.HU, 29, 31, 159),
    ("Gunnar#1165", Race.HU, 22, 31, 137),
    ("ObnoxiousDMG#1727", Race.NE, 21, 6, 124),
    ("Sacktikkla#1398", Race.NE, 12, 15, 86),
    ("kovic#21111", Race.HU, 7, 2, 83),
    ("LOSu2#1716", Race.HU, 10, 12, 72),
    ("Elkiador#1553", Race.HU, 10, 14, 64),
    # Registered RANDOM: only the random picks score, not every race played
    ("Eldrin#21596", Race.RANDOM, 2, 2, 33),
    ("EAShibby#2644", Race.RANDOM, 13, 8, 92),
    # Registered on a race: a random pick that rolled it is not a league game
    ("Solstice1221#11218", Race.OC, 86, 85, 500),
    ("tikknee#3238", Race.HU, 33, 21, 186),
]

pytestmark = pytest.mark.skipif(
    os.getenv("W3C_ORACLE") != "1", reason="set W3C_ORACLE=1 to call w3champions"
)


_state: dict[str, Any] = {}


def oracle() -> dict[str, Any]:
    """The service, the w3champions season and the GNL roster, asked for once."""
    if not _state:
        service = W3CService()
        teams = requests.get(f"{GNL_BACKEND}/teams/season/{GNL_SEASON}").json()
        roster = {
            team["id"]: {
                player["battleTag"].lower()
                for player in team["player_by_season"].get(GNL_SEASON, [])
            }
            for team in teams
        }
        _state.update(
            service=service,
            season=service.latest_season(),
            roster=roster,
            everyone=set().union(*roster.values()),
            team_of={tag: team for team, tags in roster.items() for tag in tags},
            captains=frozenset(
                captain["battleTag"].lower()
                for team in teams
                for captain in team["captains_by_season"].get(GNL_SEASON, [])
            ),
        )
    return _state


@pytest.mark.parametrize(("battle_tag", "race", "wins", "losses", "total"), EXPECTED)
def test_our_numbers_match_wc3_no(
    monkeypatch: pytest.MonkeyPatch,
    battle_tag: str,
    race: Race,
    wins: int,
    losses: int,
    total: int,
) -> None:
    """Wins, losses, ladder points and the total over the GNL S18 window."""
    monkeypatch.setattr(requests.Session, "request", REAL_REQUEST)
    state = oracle()
    service: W3CService = state["service"]

    matches, _ = service.walk_player_matches(battle_tag, state["season"], START)
    mine = [
        row
        for row in matches
        if row.battleTag.lower() == battle_tag.lower()
        and row.race is race
        and START <= row.start_time <= END
        and ladder.counted(row.duration_s)
    ]
    totals = ladder.totals(mine)

    tag = battle_tag.lower()
    opponents = frozenset(state["everyone"] - state["roster"][state["team_of"][tag]])
    captains = state["captains"]
    captain = tag in captains
    earned = achievements.earned(
        mine, totals.points, achievements.DEFAULT_PAID, opponents, captains, captain
    )

    expected_points = ladder.WIN_POINTS * wins + ladder.LOSS_POINTS * losses
    print(
        f"{battle_tag:20} {race.value:6} ours {totals.wins:4}W {totals.losses:4}L "
        f"{totals.points:5}p + {achievements.total_points(earned):4}a = "
        f"{totals.points + achievements.total_points(earned):5}   wc3.no {total:5}\n"
        f"{'':29}{', '.join(f'{a.id}:{a.points}' for a in earned)}"
    )
    assert (totals.wins, totals.losses, totals.points) == (
        wins,
        losses,
        expected_points,
    )
    assert totals.points + achievements.total_points(earned) == total
