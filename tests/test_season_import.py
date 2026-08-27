"""POST /import writes a whole season from one workbook.

The route runs the pipeline synchronously. It answers the season it
wrote, or an error envelope when the pipeline raises.
"""

import io
from typing import Any

import pandas as pd
from httpx2 import Client, Response
from sqlalchemy import func, select

from app.core.db import Session
from app.models.map import Map
from app.models.season import Season
from app.models.team import Team
from app.models.user import User
from tests.test_query_budget import count_statements

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


def _branding(
    *,
    pick_ban: str | None,
    discord_role: str | None,
    long_name: str | None,
    image: str | None,
) -> dict[str, tuple[list[str], list[list[Any]]]]:
    """The sheets whose optional cells carry branding, filled or blank."""
    return {
        "Season": (
            SHEETS["Season"][0],
            [
                [
                    None,
                    "Season 9",
                    4,
                    2,
                    pick_ban,
                    "2026-01-05",
                    "2026-02-27",
                    discord_role,
                ]
            ],
        ),
        "Teams": (
            SHEETS["Teams"][0],
            [[1, "Alpha", long_name, discord_role], [2, "Beta", "Team Beta", None]],
        ),
        "Maps": (
            ["ID", "Name", "Shortname", "Image URL"],
            [[1, "Echo Isles", "EI", image]],
        ),
    }


def test_a_blank_cell_keeps_the_stored_value(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """The second workbook leaves those cells empty, so the season, the team
    and the map keep the values the first one wrote."""
    filled = _branding(
        pick_ban="EI, LR",
        discord_role="9001",
        long_name="Team Alpha",
        image="https://example.com/ei.png",
    )
    first = _post(client, _workbook(extra=filled), auth_headers)
    assert first.status_code == 200, first.text

    blank = _branding(pick_ban=None, discord_role=None, long_name=None, image=None)
    second = _post(client, _workbook(extra=blank), auth_headers)
    assert second.status_code == 200, second.text

    with Session() as session:
        season = session.scalars(select(Season).where(Season.name == "Season 9")).one()
        team = session.scalars(select(Team).where(Team.name == "Alpha")).one()
        stored_map = session.scalars(select(Map).where(Map.shortname == "EI")).one()

    assert (season.pick_ban, season.discordRole) == ("EI, LR", "9001")
    assert (team.long_name, team.discord_role) == ("Team Alpha", "9001")
    assert stored_map.image == "https://example.com/ei.png"


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


# One transaction of bulk statements, not one transaction per row, so the
# cost of an import does not grow with the rows a sheet holds.

# The workbook below costs 25: one lookup per sheet and the writes it needs
IMPORT_STATEMENTS = 40


def _row_counts() -> dict[str, int]:
    """How many rows every table holds."""
    from sqlmodel import SQLModel

    with Session() as session:
        return {
            table.name: session.execute(
                select(func.count()).select_from(table)
            ).scalar_one()
            for table in SQLModel.metadata.sorted_tables
        }


def test_an_import_costs_a_bounded_number_of_statements(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """A whole workbook costs a fixed number of statements, whatever its
    row count."""
    with count_statements() as tally:
        response = _post(client, _workbook(extra=FANTASY_SHEETS), auth_headers)

    assert response.status_code == 200, response.text
    assert tally[0] <= IMPORT_STATEMENTS, tally[0]


def test_a_workbook_the_pipeline_cannot_read_writes_nothing(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """The Series sheet names a player the Players sheet does not carry, so
    the transaction rolls back and no season, team or player is left."""
    columns, _ = SHEETS["Series"]
    broken = {"Series": (columns, [[1, 1, 1, 9, 2, 1, 2, 1, 1, None, None, False]])}

    response = _post(client, _workbook(extra=broken), auth_headers)

    assert response.status_code == 400, response.text
    assert response.json() == {
        "error": "Series 1 names a match or a player the workbook lacks"
    }

    with Session() as session:
        assert session.scalars(select(Season)).all() == []
        assert session.scalars(select(Team)).all() == []
        assert session.scalars(select(User)).all() == []


def test_importing_the_same_workbook_twice_adds_no_row(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Every sheet matches what the first import wrote, so the second one
    updates those rows and writes none."""
    first = _post(client, _workbook(extra=FANTASY_SHEETS), auth_headers)
    assert first.status_code == 200, first.text
    after_first = _row_counts()

    second = _post(client, _workbook(extra=FANTASY_SHEETS), auth_headers)
    assert second.status_code == 200, second.text
    assert second.json()["season_id"] == first.json()["season_id"]
    assert _row_counts() == after_first


def _season_sheet(system: str) -> dict[str, tuple[list[str], list[list[Any]]]]:
    """The Season sheet of a newer export, which names its score system."""
    columns, rows = SHEETS["Season"]
    return {"Season": ([*columns, "Score System"], [[*rows[0], system]])}


def _series_sheet(player1_points: int) -> dict[str, tuple[list[str], list[list[Any]]]]:
    """A played 2-1 series. Its two point columns sum to 3 under standard
    and to 4 under helpstone."""
    columns, _ = SHEETS["Series"]
    row = [1, 1, 1, 2, 2, 1, player1_points, 1, 1, None, None, False]
    return {"Series": (columns, [row])}


def _score_system_of(name: str = "Season 9") -> str:
    with Session() as session:
        return (
            session.scalars(select(Season).where(Season.name == name))
            .one()
            .score_system
        )


def test_the_score_system_column_names_the_scale(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """The column wins over what the series imply, and here they disagree."""
    response = _post(client, _workbook(extra=_season_sheet("helpstone")), auth_headers)

    assert response.status_code == 200, response.text
    assert _score_system_of() == "helpstone"


def test_a_workbook_without_the_column_reads_helpstone_from_its_series(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """An export of the original app carries no column, so the 4 points its
    played series pay name the scale."""
    response = _post(client, _workbook(extra=_series_sheet(3)), auth_headers)

    assert response.status_code == 200, response.text
    assert _score_system_of() == "helpstone"


def test_a_workbook_without_the_column_reads_standard_from_its_series(
    client: Client, auth_headers: dict[str, str]
) -> None:
    response = _post(client, _workbook(extra=_series_sheet(2)), auth_headers)

    assert response.status_code == 200, response.text
    assert _score_system_of() == "standard"


def test_a_workbook_with_no_played_series_reads_standard(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Nothing implies a scale, so the season takes the default one."""
    columns, _ = SHEETS["Series"]
    empty = {
        "Series": (columns, [[1, 1, 1, 2, 2, 1, None, None, 1, None, None, False]])
    }

    response = _post(client, _workbook(extra=empty), auth_headers)

    assert response.status_code == 200, response.text
    assert _score_system_of() == "standard"


def test_the_score_system_parameter_overrides_the_workbook(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """The column says helpstone and the request says standard."""
    response = client.post(
        "/import",
        params={"score_system": "standard"},
        files={
            "file": (
                "season.xlsx",
                _workbook(extra=_season_sheet("helpstone")),
                "application/vnd.ms-excel",
            )
        },
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    assert _score_system_of() == "standard"


def test_a_score_system_the_scoring_rule_does_not_know_is_refused(
    client: Client, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/import",
        params={"score_system": "double"},
        files={"file": ("season.xlsx", _workbook(), "application/vnd.ms-excel")},
        headers=auth_headers,
    )

    assert response.status_code == 400, response.text
    assert response.json() == {"error": "Unknown score system: double"}

    with Session() as session:
        assert session.scalars(select(Season)).all() == []


def test_a_score_system_column_the_scoring_rule_does_not_know_is_refused(
    client: Client, auth_headers: dict[str, str]
) -> None:
    response = _post(client, _workbook(extra=_season_sheet("triple")), auth_headers)

    assert response.status_code == 400, response.text
    assert response.json() == {"error": "Unknown score system: triple"}
