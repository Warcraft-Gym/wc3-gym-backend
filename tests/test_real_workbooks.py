"""The two workbooks prod exports, imported, exported and imported again.

The sheets test_season_import builds are clean. These files carry what
MySQL holds: names with a trailing space, and a Fantasy Bets sheet with a
row repeated. The round trip is the MySQL to Postgres migration path, so
the counts must survive an export and a second import.
"""

from pathlib import Path

from httpx2 import Client
from sqlalchemy import func, select
from sqlmodel import SQLModel

from app.core.db import Session
from app.models.user import User
from app.services.season_import import import_season_workbook
from tests.conftest import empty_tables
from tests.test_season_import import SHEETS, _post, _workbook

DATA = Path(__file__).parent / "data"

# S18 imported first, then S17: the two seasons share players
TOTALS = {
    "users": 174,
    "series": 300,
    "fantasy_bets": 777,
    "matches": 30,
    "fantasy_teams": 45,
    "fantasy_team_player": 267,
}


def counts() -> dict[str, int]:
    with Session() as session:
        return {
            name: session.scalar(
                select(func.count()).select_from(SQLModel.metadata.tables[name])
            )
            or 0
            for name in TOTALS
        }


def import_file(name: str) -> int:
    """Import one workbook through the pipeline the route calls. Answers
    the repeated bet rows it dropped."""
    return import_season_workbook(
        (DATA / name).read_bytes(), create_new=True
    ).duplicate_bets


def test_the_workbooks_import_with_the_counts_prod_holds(app: object) -> None:
    assert import_file("GNL_S18_export_v2.xlsx") == 1
    assert import_file("GNL_S17_export_v2.xlsx") == 0
    assert counts() == TOTALS


def test_no_stored_name_carries_the_spaces_the_workbooks_hold(app: object) -> None:
    """Five players are written as "DerMave " and the like. Postgres
    compares those spaces, so the import must drop them."""
    import_file("GNL_S18_export_v2.xlsx")
    import_file("GNL_S17_export_v2.xlsx")

    with Session() as session:
        users = session.scalars(select(User)).all()
    assert any(user.name == "DerMave" for user in users)
    for user in users:
        for field in (user.name, user.battleTag, user.discordTag, user.discordId):
            assert field == field.strip(), field


def test_the_export_of_both_seasons_imports_into_a_fresh_database(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """The workbook the app exports is the migration file, so re-importing
    it must leave the same rows the prod workbooks wrote."""
    seasons = [
        import_season_workbook((DATA / name).read_bytes(), create_new=True).id
        for name in ("GNL_S18_export_v2.xlsx", "GNL_S17_export_v2.xlsx")
    ]
    assert counts() == TOTALS

    exports = []
    for season_id in seasons:
        resp = client.post(f"/export?season_id={season_id}", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        exports.append(resp.content)

    empty_tables()
    for content in exports:
        import_season_workbook(content, create_new=True)
    assert counts() == TOTALS


def test_a_player_without_a_discord_id_answers_400(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """The exporter writes an empty cell for a null discordId, so the
    import must name the row instead of raising a validation error."""
    columns, rows = SHEETS["Players"]
    blank = [rows[0], [*rows[1][:4], None, *rows[1][5:]]]

    response = _post(
        client, _workbook(extra={"Players": (columns, blank)}), auth_headers
    )

    assert response.status_code == 400, response.text
    assert response.json() == {
        "error": "Player 2 of the Players sheet has no discordId"
    }
