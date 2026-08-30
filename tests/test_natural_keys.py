"""The natural keys the importers match on, and what they leave free.

Both importers find an existing row by a natural key. Without an index a
second row can hold the same key, and the importer then picks one of them at
random. Every key below refuses the repeat, and the lookups fold case so the
importer updates the row it already has instead of meeting the index.
"""

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel
from starlette.testclient import TestClient as Client

from app.core.db import Session
from app.models.discord_role_binding import DiscordRoleBinding
from app.models.enums import Race, RoleKind
from app.models.fantasy_team import FantasyTeam
from app.models.map import Map
from app.models.match import Match
from app.models.season import Season
from app.models.series import Series
from app.models.team import Team
from app.models.user import User
from tests.test_season_import import SHEETS, _post, _workbook

type Rows = Callable[[dict[str, Any]], list[SQLModel]]


def user(tag: str, **kwargs: Any) -> User:  # noqa: ANN401  # model fields
    return User(
        name=kwargs.pop("name", tag),
        battleTag=tag,
        discordTag=kwargs.pop("discordTag", tag),
        discordId="0",
        race=Race.HU,
        **kwargs,
    )


# Each pair repeats one natural key. The case and the spaces differ because
# neither makes a new player, season, team or map.
REPEATS: dict[str, Rows] = {
    "users.battleTag": lambda _: [user("Repeat#1"), user(" repeat#1 ", name="Other")],
    "users.discordTag": lambda _: [
        user("A#1", discordTag="Dup"),
        user("B#2", discordTag="dup"),
    ],
    "seasons.name": lambda _: [
        Season(name="Season 9", number_weeks=4, series_per_week=2),
        Season(name="season 9", number_weeks=4, series_per_week=2),
    ],
    "discord_role_binding.discord_role": lambda _: [
        DiscordRoleBinding(kind=RoleKind.coach, discord_role="7788"),
        DiscordRoleBinding(kind=RoleKind.fantasy, discord_role="7788"),
    ],
    "maps.shortname": lambda _: [
        Map(name="Echo Isles", shortname="EI"),
        Map(name="Echo Isles Remake", shortname="ei"),
    ],
    "fantasy_teams.name": lambda seeded: [
        FantasyTeam(
            name="Repeat",
            season_id=seeded["season_id"],
            captain_id=seeded["player_ids"][1],
        ),
        FantasyTeam(
            name="repeat",
            season_id=seeded["season_id"],
            captain_id=seeded["player_ids"][2],
        ),
    ],
    "fantasy_teams.captain_id": lambda seeded: [
        FantasyTeam(
            name="First",
            season_id=seeded["season_id"],
            captain_id=seeded["player_ids"][1],
        ),
        FantasyTeam(
            name="Second",
            season_id=seeded["season_id"],
            captain_id=seeded["player_ids"][1],
        ),
    ],
    "matches.playday": lambda seeded: [
        Match(
            team1_id=seeded["team_a_id"],
            team2_id=seeded["team_b_id"],
            season_id=seeded["season_id"],
            playday=9,
        ),
        Match(
            team1_id=seeded["team_a_id"],
            team2_id=seeded["team_b_id"],
            season_id=seeded["season_id"],
            playday=9,
        ),
    ],
    "series.players": lambda seeded: [
        Series(
            match_id=seeded["match_id"],
            player1_id=seeded["player_ids"][0],
            player2_id=seeded["player_ids"][3],
            host_player_id=seeded["player_ids"][0],
        )
        for _ in range(2)
    ],
}


@pytest.mark.parametrize("key", list(REPEATS))
def test_the_database_refuses_a_repeated_natural_key(
    key: str, seeded: dict[str, Any]
) -> None:
    """The second row of each pair is the one the index refuses."""
    with Session() as session, pytest.raises(IntegrityError):
        for row in REPEATS[key](seeded):
            session.add(row)
            session.flush()


def test_a_blank_discord_tag_may_repeat(seeded: dict[str, Any]) -> None:
    """An import writes a blank tag for a bettor who has none, and blank
    means unknown, so it names nobody and cannot repeat anybody."""
    with Session() as session:
        session.add_all(
            [user("Blank#1", discordTag=""), user("Blank#2", discordTag="")]
        )
        session.commit()


def test_two_clubs_may_share_a_short_name(seeded: dict[str, Any]) -> None:
    """A club is its Discord role binding, not its short name, so a short name
    a folded club used is free for the next one."""
    with Session() as session:
        session.add_all([Team(name="PP"), Team(name="PP")])
        session.commit()


def test_a_repeated_key_answers_409_and_says_which_conflict(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A battle tag another player holds is a conflict with a row, not a
    reference from one, and the message says so."""
    body = {
        "name": "Impostor",
        "battleTag": "P1#1111",
        "discordTag": "impostor",
        "discordId": "8",
        "race": "HU",
    }
    resp = client.post("/users", json=body, headers=auth_headers)

    assert resp.status_code == 409, resp.text
    assert resp.json() == {"error": "Row already exists"}


def _shouted(sheet: str, column: int) -> tuple[list[str], list[list[Any]]]:
    """The sheet with one of its columns typed in upper case."""
    header, rows = SHEETS[sheet]
    return header, [
        [
            value.upper() if index == column and isinstance(value, str) else value
            for index, value in enumerate(row)
        ]
        for row in rows
    ]


def _counts() -> dict[str, int]:
    with Session() as session:
        return {
            model.__name__: len(session.scalars(select(model)).all())
            for model in (Season, Team, User)
        }


def test_the_import_matches_the_rows_it_wrote_whatever_the_case(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """The same workbook typed in another case updates the season, teams and
    players it wrote rather than writing a second set beside them."""
    assert _post(client, _workbook(), auth_headers).status_code == 200
    before = _counts()

    shouted = _workbook(
        extra={
            "Season": _shouted("Season", 1),
            "Teams": _shouted("Teams", 1),
            "Players": _shouted("Players", 2),
        }
    )
    assert _post(client, shouted, auth_headers).status_code == 200, "the shouted import"

    assert _counts() == before
