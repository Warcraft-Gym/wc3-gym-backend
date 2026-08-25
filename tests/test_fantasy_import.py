"""The fantasy team import reads the race a captain typed into a form.

The sheet carries free text such as "Night Elf". The database column holds
a Race member, so the import has to translate.
"""

import io
from typing import Any

import pandas as pd
import pytest
from sqlalchemy import select
from starlette.testclient import TestClient as Client

from app.core.db import Session
from app.models.enums import Race
from app.models.fantasy_bet import FantasyBet
from app.models.fantasy_team import FantasyTeam
from app.models.series import Series
from app.models.user import User
from tests.test_query_budget import count_statements


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Human", Race.HU),
        ("human", Race.HU),
        ("HU", Race.HU),
        ("Orc", Race.OC),
        ("Night Elf", Race.NE),
        ("night  elf", Race.NE),
        ("NE", Race.NE),
        ("Undead", Race.UD),
        ("Random", Race.RANDOM),
        ("rd", Race.RANDOM),
    ],
)
def test_race_from_text(text: str, expected: Race) -> None:
    assert Race.from_text(text) == expected


def test_race_from_text_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown race: Elf"):
        Race.from_text("Elf")


# Columns 2 to 9 hold the eight drafted players. The seed has four, and the
# import caches a player by name, so each one can appear twice.
DRAFTED = ["P1", "P2", "P3", "P4", "P1", "P2", "P3", "P4"]


def _teams_sheet(rows: list[list[Any]]) -> io.BytesIO:
    """A "Formatted Responses" sheet. The import reads columns by position."""
    frame = pd.DataFrame(rows, columns=[f"c{i}" for i in range(12)])
    stream = io.BytesIO()
    frame.to_excel(stream, sheet_name="Formatted Responses", index=False)
    stream.seek(0)
    return stream


def _bets_sheets(matches: list[list[Any]], bets: list[list[Any]]) -> io.BytesIO:
    """A "Betting Matches" and a "Bets" sheet. Columns read by position."""
    stream = io.BytesIO()
    with pd.ExcelWriter(stream) as writer:
        pd.DataFrame(matches, columns=[f"c{i}" for i in range(3)]).to_excel(
            writer, sheet_name="Betting Matches", index=False
        )
        pd.DataFrame(bets, columns=[f"c{i}" for i in range(4)]).to_excel(
            writer, sheet_name="Bets", index=False
        )
    stream.seek(0)
    return stream


def test_import_fantasy_teams_reads_the_race(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    row: list[Any] = ["Night Owls", "p1", *DRAFTED, "Alpha", "Night Elf"]
    sheet = _teams_sheet([row])

    response = client.post(
        "/fantasy/import/teams",
        params={"season_id": str(seeded["season_id"])},
        files={"file": ("teams.xlsx", sheet, "application/vnd.ms-excel")},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text

    with Session() as session:
        team = session.scalars(
            select(FantasyTeam).where(FantasyTeam.name == "Night Owls")
        ).one()
        assert team.drafted_race == Race.NE


def test_import_fantasy_teams_rejects_an_unknown_race(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    row: list[Any] = ["Night Owls", "p1", *[None] * 8, "Alpha", "Elf"]
    sheet = _teams_sheet([row])

    response = client.post(
        "/fantasy/import/teams",
        params={"season_id": str(seeded["season_id"])},
        files={"file": ("teams.xlsx", sheet, "application/vnd.ms-excel")},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert response.json() == {"error": "Unknown race: Elf"}


def test_import_fantasy_bets_stores_a_bet(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    sheet = _bets_sheets([[1, "P1", "P3"]], [[1, "p2", "P1", 7]])

    response = client.post(
        "/fantasy/import/bets",
        params={"season_id": str(seeded["season_id"])},
        files={"file": ("bets.xlsx", sheet, "application/vnd.ms-excel")},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text

    with Session() as session:
        bet = session.scalars(
            select(FantasyBet).where(FantasyBet.user_id == seeded["player_ids"][1])
        ).one()
        assert bet.series_id == seeded["series_played_id"]
        assert bet.winner_id == seeded["player_ids"][0]
        assert bet.bet_points == 7


def test_import_fantasy_teams_names_the_row_it_rejects(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """A sheet the import cannot read answers 400 and names the team."""
    row: list[Any] = ["Night Owls", None, *DRAFTED, "Alpha", "Night Elf"]
    sheet = _teams_sheet([row])

    response = client.post(
        "/fantasy/import/teams",
        params={"season_id": str(seeded["season_id"])},
        files={"file": ("teams.xlsx", sheet, "application/vnd.ms-excel")},
        headers=auth_headers,
    )

    assert response.status_code == 400, response.text
    assert response.json() == {"error": "Team without captain: Night Owls"}


def test_the_import_creates_a_captain_it_cannot_find(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """A captain on no roster is written from the tag the sheet carries."""
    row: list[Any] = ["Night Owls", "newcap", *DRAFTED, "Alpha", "Orc"]

    response = client.post(
        "/fantasy/import/teams",
        params={"season_id": str(seeded["season_id"])},
        files={"file": ("teams.xlsx", _teams_sheet([row]), "application/vnd.ms-excel")},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text

    with Session() as session:
        captain = session.scalars(select(User).where(User.discordTag == "newcap")).one()
        team = session.scalars(
            select(FantasyTeam).where(FantasyTeam.name == "Night Owls")
        ).one()
    assert captain.battleTag == "Fantasy_User"
    assert team.captain_id == captain.id


# A Google Form entry is typed by hand, so a lookup folds the case of the
# text it matches on. MySQL collated the per-row queries that way.


def test_a_captain_matches_a_discord_tag_in_another_case(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """The sheet says "P1", the database says "p1", and no second user is
    written for the same captain."""
    row: list[Any] = ["Night Owls", " P1 ", *DRAFTED, "Alpha", "Orc"]

    response = client.post(
        "/fantasy/import/teams",
        params={"season_id": str(seeded["season_id"])},
        files={"file": ("teams.xlsx", _teams_sheet([row]), "application/vnd.ms-excel")},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text

    with Session() as session:
        team = session.scalars(
            select(FantasyTeam).where(FantasyTeam.name == "Night Owls")
        ).one()
        assert team.captain_id == seeded["player_ids"][0]
        assert len(session.scalars(select(User)).all()) == len(seeded["player_ids"])


def test_a_drafted_player_matches_a_name_in_another_case(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """The sheet says "p1", the database says "P1"."""
    drafted = [name.lower() for name in DRAFTED]
    row: list[Any] = ["Night Owls", "p1", *drafted, "Alpha", "Orc"]

    response = client.post(
        "/fantasy/import/teams",
        params={"season_id": str(seeded["season_id"])},
        files={"file": ("teams.xlsx", _teams_sheet([row]), "application/vnd.ms-excel")},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text

    with Session() as session:
        team = session.scalars(
            select(FantasyTeam).where(FantasyTeam.name == "Night Owls")
        ).one()
        drafted_ids = {player.user_id for player in team.drafted_players}
    assert drafted_ids == set(seeded["player_ids"])


def test_a_drafted_team_matches_a_name_in_another_case(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """The sheet says "alpha", the database says "Alpha"."""
    row: list[Any] = ["Night Owls", "p1", *DRAFTED, "alpha", "Orc"]

    response = client.post(
        "/fantasy/import/teams",
        params={"season_id": str(seeded["season_id"])},
        files={"file": ("teams.xlsx", _teams_sheet([row]), "application/vnd.ms-excel")},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text

    with Session() as session:
        team = session.scalars(
            select(FantasyTeam).where(FantasyTeam.name == "Night Owls")
        ).one()
    assert team.drafted_team_id == seeded["team_a_id"]


def test_a_team_sheet_the_import_cannot_read_writes_nothing(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """The second row names a player the database does not hold, so the first
    row leaves neither a fantasy team nor a captain behind."""
    rows: list[list[Any]] = [
        ["Night Owls", "p1", *DRAFTED, "Alpha", "Night Elf"],
        ["Ghosts", "newcap", *["Ghost"] * 8, "Beta", "Orc"],
    ]

    response = client.post(
        "/fantasy/import/teams",
        params={"season_id": str(seeded["season_id"])},
        files={"file": ("teams.xlsx", _teams_sheet(rows), "application/vnd.ms-excel")},
        headers=auth_headers,
    )

    assert response.status_code == 400, response.text
    assert response.json() == {"error": "Could not find player by name: Ghost"}

    with Session() as session:
        team = session.scalars(select(FantasyTeam)).one()
        assert team.name == "The Optimists"
        unknown = session.scalars(select(User).where(User.discordTag == "newcap")).all()
        assert unknown == []


def test_a_bet_sheet_the_import_cannot_read_writes_nothing(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """The second bet names a player the database does not hold, so neither
    the first bet nor the fantasy match flag is left behind."""
    sheet = _bets_sheets([[1, "P1", "P3"]], [[1, "p2", "P1", 7], [1, "p2", "Ghost", 5]])

    response = client.post(
        "/fantasy/import/bets",
        params={"season_id": str(seeded["season_id"])},
        files={"file": ("bets.xlsx", sheet, "application/vnd.ms-excel")},
        headers=auth_headers,
    )

    assert response.status_code == 400, response.text
    assert response.json() == {
        "error": "No or multiple users found for bet player[Ghost]: []"
    }

    with Session() as session:
        stored = session.scalars(
            select(FantasyBet).where(FantasyBet.user_id == seeded["player_ids"][1])
        ).all()
        assert stored == []
        series = session.get(Series, seeded["series_played_id"])
        assert not series.is_fantasy_match


# One transaction of bulk statements, not one transaction per row, so the
# cost of an import does not grow with the rows a sheet holds.

# The team sheet below costs 8, the two bet sheets 10
TEAM_STATEMENTS = 12
BET_STATEMENTS = 14


def test_a_team_import_costs_a_bounded_number_of_statements(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """Two teams of eight drafted players each, one lookup per table."""
    rows: list[list[Any]] = [
        ["Night Owls", "p1", *DRAFTED, "Alpha", "Night Elf"],
        ["Day Owls", "p3", *DRAFTED, "Beta", "Orc"],
    ]

    with count_statements() as tally:
        response = client.post(
            "/fantasy/import/teams",
            params={"season_id": str(seeded["season_id"])},
            files={
                "file": ("teams.xlsx", _teams_sheet(rows), "application/vnd.ms-excel")
            },
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    assert tally[0] <= TEAM_STATEMENTS, tally[0]


def test_a_bet_import_costs_a_bounded_number_of_statements(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """Two fantasy matches and two bets, one lookup per table."""
    sheet = _bets_sheets(
        [[1, "P1", "P3"], [1, "P2", "P4"]], [[1, "p2", "P1", 7], [1, "p1", "P2", 5]]
    )

    with count_statements() as tally:
        response = client.post(
            "/fantasy/import/bets",
            params={"season_id": str(seeded["season_id"])},
            files={"file": ("bets.xlsx", sheet, "application/vnd.ms-excel")},
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    assert tally[0] <= BET_STATEMENTS, tally[0]
