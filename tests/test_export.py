"""What POST /export answers and what its workbook holds.

The export is a per-season migration file, not a backup: it carries ten
sheets and the import reads the same ten back. Twelve tables stay out of
it, so a workbook cannot rebuild a database.
"""

from io import BytesIO
from typing import Any

import openpyxl
import pytest
from httpx2 import Client

from app.api.routes import import_export

SHEETS = [
    "Season",
    "Maps",
    "Teams",
    "Players",
    "Matches",
    "Series",
    "Fantasy Teams",
    "Fantasy Team Players",
    "Fantasy Bets",
    "Fantasy Users",
]


def workbook_of(content: bytes) -> openpyxl.Workbook:
    """The answered bytes, read back as a workbook."""
    return openpyxl.load_workbook(BytesIO(content))


def test_export_needs_a_season_id(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The parameter is required, so a call without one answers 422."""
    resp = client.post("/export", headers=auth_headers)
    assert resp.status_code == 422


def test_export_rejects_a_season_id_that_is_not_a_number(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    resp = client.post("/export?season_id=latest", headers=auth_headers)
    assert resp.status_code == 422


def test_export_answers_404_for_an_unknown_season(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    resp = client.post("/export?season_id=9999", headers=auth_headers)
    assert resp.status_code == 404


def test_export_needs_an_admin(client: Client, seeded: dict[str, Any]) -> None:
    resp = client.post(f"/export?season_id={seeded['season_id']}")
    assert resp.status_code == 401


def test_export_answers_the_ten_sheets(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The workbook holds every sheet the import reads, in order."""
    resp = client.post(f"/export?season_id={seeded['season_id']}", headers=auth_headers)
    assert resp.status_code == 200

    workbook = workbook_of(resp.content)
    assert workbook.sheetnames == SHEETS


def add_outsider(seeded: dict[str, Any]) -> int:
    """A fantasy captain and bettor of the season who is on no team roster."""
    from app.core.db import Session
    from app.models.enums import Race
    from app.models.fantasy_bet import FantasyBet
    from app.models.fantasy_team import FantasyTeam
    from app.models.user import User

    with Session() as session:
        outsider = User(
            name="Cap",
            battleTag="Cap#7777",
            discordTag="cap",
            discordId="7",
            race=Race.NE,
        )
        session.add(outsider)
        session.flush()
        session.add_all(
            [
                FantasyTeam(
                    name="The Outsiders",
                    season_id=seeded["season_id"],
                    captain_id=outsider.id,
                    drafted_team_id=seeded["team_a_id"],
                    drafted_race=Race.HU,
                ),
                FantasyBet(
                    season_id=seeded["season_id"],
                    series_id=seeded["series_played_id"],
                    user_id=outsider.id,
                    winner_id=seeded["player_ids"][0],
                    bet_points=10,
                ),
            ]
        )
        session.commit()
        return outsider.id


def test_the_fantasy_users_sheet_holds_the_users_who_are_on_no_roster(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The seeded captain and bettors are rostered, so only the outsider
    lands in the sheet."""
    outsider_id = add_outsider(seeded)

    resp = client.post(f"/export?season_id={seeded['season_id']}", headers=auth_headers)
    assert resp.status_code == 200

    sheet = workbook_of(resp.content)["Fantasy Users"]
    rows = list(sheet.values)
    assert rows[0] == ("ID", "Name", "Battle Tag", "Discord Tag", "Discord ID")
    assert rows[1:] == [(outsider_id, "Cap", "Cap#7777", "cap", "7")]


def add_bets(seeded: dict[str, Any], count: int) -> None:
    """Put count more bets in the seeded season, each on its own series."""
    from app.core.db import Session
    from app.models.fantasy_bet import FantasyBet
    from app.models.series import Series

    with Session() as session:
        for _ in range(count):
            series = Series(
                match_id=seeded["match_id"],
                player1_id=seeded["player_ids"][0],
                player2_id=seeded["player_ids"][2],
                host_player_id=seeded["player_ids"][0],
            )
            session.add(series)
            session.flush()
            session.add(
                FantasyBet(
                    season_id=seeded["season_id"],
                    series_id=series.id,
                    user_id=seeded["player_ids"][0],
                    winner_id=seeded["player_ids"][0],
                    bet_points=10,
                )
            )
        session.commit()


def test_the_export_reads_every_bet_over_several_pages(
    client: Client,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Six bets over pages of two land in the sheet once each."""
    monkeypatch.setattr(import_export, "BET_PAGE", 2)
    add_bets(seeded, 5)

    resp = client.post(f"/export?season_id={seeded['season_id']}", headers=auth_headers)
    assert resp.status_code == 200

    sheet = workbook_of(resp.content)["Fantasy Bets"]
    rows = list(sheet.values)[1:]
    ids = [row[0] for row in rows]
    assert len(ids) == 6
    assert len(set(ids)) == 6
