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
