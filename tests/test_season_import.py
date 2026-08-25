"""POST /import writes a whole season from one workbook.

The route runs the pipeline synchronously. It answers the season it
wrote, or an error envelope when the pipeline raises.
"""

import io
from typing import Any

import pandas as pd
from httpx2 import Client, Response
from sqlalchemy import select

from app.core.db import Session
from app.models.season import Season
from app.models.team import Team
from app.models.user import User

SHEETS: dict[str, tuple[list[str], list[list[Any]]]] = {
    "Season": (
        [
            "ID",
            "Name",
            "Number of Weeks",
            "Series Per Week",
            "Pick Ban",
            "Start Date",
            "End Date",
            "Discord Role",
        ],
        [[None, "Season 9", 4, 2, None, "2026-01-05", "2026-02-27", None]],
    ),
    "Teams": (
        ["ID", "Name", "Long Name", "Discord Role"],
        [[1, "Alpha", "Team Alpha", None], [2, "Beta", "Team Beta", None]],
    ),
    "Players": (
        [
            "ID",
            "Name",
            "Battle Tag",
            "Discord Tag",
            "Discord ID",
            "Race",
            "MMR",
            "Country",
            "Fantasy Tier",
            "Team ID",
        ],
        [
            [1, "P1", "P1#1111", "p1", 1, "HU", 1500, "DE", 1, 1],
            [2, "P2", "P2#2222", "p2", 2, "OC", 1400, "DE", 1, 2],
        ],
    ),
    "Matches": (
        [
            "ID",
            "Team1 ID",
            "Team2 ID",
            "Playday",
            "Team1 Score",
            "Team2 Score",
            "Fixed Map ID",
            "Date Frame",
        ],
        [[1, 1, 2, 1, 2, 1, None, None]],
    ),
    "Series": (
        [
            "ID",
            "Match ID",
            "Player1 ID",
            "Player2 ID",
            "Player1 Score",
            "Player2 Score",
            "Player1 Points",
            "Player2 Points",
            "Host Player ID",
            "Date Time",
            "Caster",
            "Is Fantasy Match",
        ],
        [[1, 1, 1, 2, 2, 1, 2, 1, 1, None, None, False]],
    ),
    "Fantasy Bets": (
        [
            "ID",
            "Season ID",
            "Series ID",
            "User ID",
            "Winner ID",
            "Bet Points",
            "Bet Result",
        ],
        [[1, 1, 1, 1, 1, 10, None], [2, 1, 1, 2, 2, 20, None]],
    ),
}


FANTASY_SHEETS: dict[str, tuple[list[str], list[list[Any]]]] = {
    "Fantasy Users": (
        ["ID", "Name", "Battle Tag", "Discord Tag", "Discord ID"],
        [
            [1, "P1", "P1#1111", "p1", 1],
            [7, "Cap", "Cap#7777", "cap", 7],
            [8, "Newcomer", "New#8888", "new", 8],
        ],
    ),
    "Fantasy Teams": (
        ["ID", "Name", "Season ID", "Captain ID", "Drafted Team ID", "Drafted Race"],
        [[1, "The Outsiders", 1, 7, 1, "HU"], [2, "The Newcomers", 1, 8, 2, "OC"]],
    ),
}


def _workbook(
    *,
    without: str | None = None,
    season_id: int | None = None,
    extra: dict[str, tuple[list[str], list[list[Any]]]] | None = None,
) -> io.BytesIO:
    """A season export. `without` drops one sheet the pipeline reads,
    `season_id` names the season it writes into instead of a new one, and
    `extra` adds sheets the default workbook does not carry."""
    stream = io.BytesIO()
    with pd.ExcelWriter(stream) as writer:
        for name, (columns, rows) in {**SHEETS, **(extra or {})}.items():
            if name == without:
                continue
            if name == "Season" and season_id is not None:
                rows = [[season_id, *rows[0][1:]]]
            pd.DataFrame(rows, columns=columns).to_excel(
                writer, sheet_name=name, index=False
            )
    stream.seek(0)
    return stream


def _post(client: Client, book: io.BytesIO, headers: dict[str, str]) -> Response:
    return client.post(
        "/import",
        files={"file": ("season.xlsx", book, "application/vnd.ms-excel")},
        headers=headers,
    )


def test_a_synchronous_import_writes_the_season(
    client: Client, auth_headers: dict[str, str]
) -> None:
    response = _post(client, _workbook(), auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["message"] == "Season imported successfully"
    assert body["season_name"] == "Season 9"

    with Session() as session:
        season = session.scalars(select(Season).where(Season.name == "Season 9")).one()
        assert season.id == body["season_id"]
        assert season.number_weeks == 4
        assert len(session.scalars(select(Team)).all()) == 2
        assert len(session.scalars(select(User)).all()) == 2


def test_a_synchronous_import_that_fails_answers_an_error(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """The workbook has no Players sheet, so the pipeline raises after it
    has written the season."""
    response = _post(client, _workbook(without="Players"), auth_headers)

    assert response.status_code == 500, response.text
    assert response.json() == {"error": "Internal Server Error"}


def test_an_old_background_parameter_runs_the_import(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """The route has no background parameter, so an old caller gets the
    synchronous answer."""
    response = client.post(
        "/import",
        params={"background": "true"},
        files={"file": ("season.xlsx", _workbook(), "application/vnd.ms-excel")},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["message"] == "Season imported successfully"

    with Session() as session:
        assert session.scalars(select(Season).where(Season.name == "Season 9")).one()


def test_a_second_import_updates_the_bets_instead_of_adding_them(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """The pipeline finds the stored bets in its one lookup, so importing the
    same workbook twice leaves two bets, not four."""
    from app.models.fantasy_bet import FantasyBet

    first = _post(client, _workbook(), auth_headers)
    assert first.status_code == 200, first.text
    season_id = first.json()["season_id"]

    second = _post(client, _workbook(season_id=season_id), auth_headers)
    assert second.status_code == 200, second.text
    assert second.json()["season_id"] == season_id

    with Session() as session:
        bets = session.scalars(select(FantasyBet)).all()
    assert len(bets) == 2
    assert sorted(bet.bet_points for bet in bets) == [10, 20]


def _add_captain() -> None:
    """A user who is on no roster, so only the Fantasy Users sheet names him."""
    from app.models.enums import Race

    with Session() as session:
        session.add(
            User(
                name="Cap",
                battleTag="Cap#7777",
                discordTag="cap",
                discordId="7",
                race=Race.NE,
            )
        )
        session.commit()


def test_the_fantasy_users_sheet_maps_a_captain_and_creates_a_missing_one(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Both fantasy teams get their captain: one from the database, one
    created from the sheet."""
    from app.models.fantasy_team import FantasyTeam

    _add_captain()

    response = _post(client, _workbook(extra=FANTASY_SHEETS), auth_headers)
    assert response.status_code == 200, response.text

    with Session() as session:
        captain = session.scalars(
            select(User).where(User.battleTag == "Cap#7777")
        ).one()
        created = session.scalars(
            select(User).where(User.battleTag == "New#8888")
        ).one()
        teams = session.scalars(select(FantasyTeam)).all()
        assert len(session.scalars(select(User)).all()) == 4

    assert created.name == "Newcomer"
    assert created.discordTag == "new"
    assert created.discordId == "8"
    assert sorted(team.captain_id for team in teams) == sorted([captain.id, created.id])


def test_an_import_without_the_fantasy_users_sheet_still_writes_the_season(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """An older export has no such sheet, so its unmapped captains are
    skipped and the season is written all the same."""
    from app.models.fantasy_team import FantasyTeam

    _add_captain()

    response = _post(
        client,
        _workbook(extra=FANTASY_SHEETS, without="Fantasy Users"),
        auth_headers,
    )
    assert response.status_code == 200, response.text

    with Session() as session:
        assert session.scalars(select(Season).where(Season.name == "Season 9")).one()
        assert session.scalars(select(FantasyTeam)).all() == []
        assert len(session.scalars(select(User)).all()) == 3
