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
}


def _workbook(*, without: str | None = None) -> io.BytesIO:
    """A season export. `without` drops one sheet the pipeline reads."""
    stream = io.BytesIO()
    with pd.ExcelWriter(stream) as writer:
        for name, (columns, rows) in SHEETS.items():
            if name == without:
                continue
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
