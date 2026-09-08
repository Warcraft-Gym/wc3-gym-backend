"""A series records the race a side played when it was not his signup race.

A player may play one series on another race. The series holds that off race
and reads null when he played the race he signed the season up on, so every
answer resolves a side's race from the two. The stored column and the resolved
answer take different names on purpose: the admin edit and the Discord score
command both send the whole series back, and a write model that named the
resolved race would pin every edited row.
"""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import Client

from app.core.db import Session
from app.models.enums import Race
from app.models.relationships import DBUserSeasonSignup
from app.models.series import Series


@pytest.fixture
def league(app: FastAPI) -> dict[str, Any]:
    """The seeded league, with both sides of the played series registered."""
    from tests.seed import seed_league

    with Session.begin() as session:
        seeded = seed_league(session)
        session.add_all(
            [
                DBUserSeasonSignup(
                    user_id=seeded["player_ids"][0],
                    season_id=seeded["season_id"],
                    race=Race.UD,
                ),
                DBUserSeasonSignup(
                    user_id=seeded["player_ids"][2],
                    season_id=seeded["season_id"],
                    race=Race.NE,
                ),
            ]
        )
    return seeded


def report_off_race(series_id: int, **sides: Race | None) -> None:
    with Session.begin() as session:
        series = session.get(Series, series_id)
        assert series is not None
        for field, race in sides.items():
            setattr(series, field, race)


def stored_off_races(series_id: int) -> tuple[Race | None, Race | None]:
    with Session() as session:
        series = session.get(Series, series_id)
        assert series is not None
        return series.player1_off_race, series.player2_off_race


def test_a_side_reads_its_signup_race_until_it_reports_an_off_race(
    client: Client, league: dict[str, Any]
) -> None:
    series = client.get(f"/series/{league['series_played_id']}").json()
    assert (series["player1_race"], series["player1_off_race"]) == ("UD", None)
    assert (series["player2_race"], series["player2_off_race"]) == ("NE", None)

    report_off_race(league["series_played_id"], player1_off_race=Race.OC)
    series = client.get(f"/series/{league['series_played_id']}").json()
    assert (series["player1_race"], series["player1_off_race"]) == ("OC", "OC")
    # The other side is untouched, and still reads the race he signed up on
    assert (series["player2_race"], series["player2_off_race"]) == ("NE", None)


def test_a_side_the_season_holds_no_signup_for_reads_no_race(
    client: Client, league: dict[str, Any]
) -> None:
    """Neither side of the open series registered, so the page draws no icon."""
    series = client.get(f"/series/{league['series_open_id']}").json()
    assert series["player1_race"] is None
    assert series["player2_race"] is None


def test_a_draft_series_carries_the_race_each_side_plays(
    league: dict[str, Any],
) -> None:
    """A draft has no result and so no off race, but the same field names it,
    so the tables read one race whether the series is drafted or played."""
    from app.models.draft_series import DraftSeries
    from app.services.draft_series import DraftSeriesService

    with Session.begin() as session:
        session.add(
            DraftSeries(
                match_id=league["match_id"],
                player1_id=league["player_ids"][0],
                player2_id=league["player_ids"][1],
                host_player_id=league["player_ids"][0],
            )
        )
    draft = DraftSeriesService().get_by_match_id(league["match_id"])[0]
    assert draft.player1_race == "UD"
    # Player 2 never registered for the season
    assert draft.player2_race is None


def test_an_echoed_answer_leaves_the_stored_off_race_alone(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """The admin edit sends the whole answer back. The resolved race is on no
    write model, so an echo can neither pin a null row nor clear a stored one."""
    series_id = league["series_played_id"]
    answer = client.get(f"/series/{series_id}").json()
    assert answer["player1_race"] == "UD"

    resp = client.put(f"/series/{series_id}", json=answer, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert stored_off_races(series_id) == (None, None)

    report_off_race(series_id, player1_off_race=Race.OC)
    answer = client.get(f"/series/{series_id}").json()
    resp = client.put(f"/series/{series_id}", json=answer, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert stored_off_races(series_id) == (Race.OC, None)


def test_an_off_race_that_names_the_signup_race_is_not_stored(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """A side who played the race he signed up on is no exception, so the row
    stays null and no page marks him."""
    series_id = league["series_played_id"]
    resp = client.put(
        f"/series/{series_id}", json={"player1_off_race": "UD"}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["player1_off_race"] is None
    assert resp.json()["player1_race"] == "UD"
    assert stored_off_races(series_id) == (None, None)


def test_a_player_reports_the_race_he_played(
    client: Client, member: Callable[..., dict[str, str]], league: dict[str, Any]
) -> None:
    series_id = league["series_played_id"]
    resp = client.put(
        f"/player-series/{series_id}",
        data={"player1_off_race": "OC"},
        headers=member("1"),
    )
    assert resp.status_code == 200, resp.text
    assert stored_off_races(series_id) == (Race.OC, None)
    assert resp.json()["player1_race"] == "OC"

    # An empty field takes a wrong report back
    resp = client.put(
        f"/player-series/{series_id}",
        data={"player1_off_race": ""},
        headers=member("1"),
    )
    assert resp.status_code == 200, resp.text
    assert stored_off_races(series_id) == (None, None)


def test_a_reported_race_that_is_not_a_race_is_refused(
    client: Client, member: Callable[..., dict[str, str]], league: dict[str, Any]
) -> None:
    resp = client.put(
        f"/player-series/{league['series_played_id']}",
        data={"player1_off_race": "Gnome"},
        headers=member("1"),
    )
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_the_weekly_race_tally_counts_the_race_played(
    client: Client, league: dict[str, Any]
) -> None:
    """The fantasy race points read the race of the series, not the profile
    race and not the signup race the side did not play that week."""
    breakdown = f"/fantasy/teams/{league['fantasy_team_id']}/season/{league['season_id']}/breakdown"
    before = client.get(breakdown).json()["race_breakdown"]

    # P1 signed up UD and beat P3, so only UD scores the week
    assert set(before["all_race_points"]) == {"UD"}

    report_off_race(league["series_played_id"], player1_off_race=Race.HU)
    after = client.get(breakdown).json()["race_breakdown"]
    # The win moves off UD and onto the race he played
    assert set(after["all_race_points"]) == {"HU"}
    assert after["race"] == "HU"
    assert after["total_points"] == before["all_race_points"]["UD"]


def test_match_history_names_the_race_the_opponent_played(
    client: Client, member: Callable[..., dict[str, str]], league: dict[str, Any]
) -> None:
    report_off_race(league["series_played_id"], player2_off_race=Race.OC)
    history = client.get("/player-history", headers=member("1")).json()
    opponents = {row["name"]: row["race"] for row in history["opponents"]}
    assert opponents["P3"] == "OC"


def test_the_series_sheet_carries_the_off_race_both_ways(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """An export and an import of the same workbook keep the off race, so a
    season that moves between databases does not lose it."""
    from tests.test_export import workbook_of

    series_id = league["series_played_id"]
    report_off_race(series_id, player1_off_race=Race.OC)

    season_id = league["season_id"]
    resp = client.post(f"/export?season_id={season_id}", headers=auth_headers)
    assert resp.status_code == 200
    rows = list(workbook_of(resp.content)["Series"].values)
    column = rows[0].index("Player1 Off Race")
    assert {row[0]: row[column] for row in rows[1:]}[series_id] == "OC"

    # The same workbook read back into an empty database keeps the race
    report_off_race(series_id, player1_off_race=None)
    imported = client.post(
        "/import",
        files={"file": ("season.xlsx", resp.content)},
        headers=auth_headers,
    )
    assert imported.status_code == 200, imported.text
    assert stored_off_races(series_id)[0] == Race.OC


def test_only_the_named_modules_read_the_off_race_column(
    league: dict[str, Any],
) -> None:
    """A series off race resolves in app.services.derived and nowhere else. A
    reader that walks the column itself reads null for every ordinary series,
    so this test names the modules that are allowed to. The ladder's own
    off race is a different thing and does not match.
    """
    import app as app_package

    allowed = {
        "api/routes/import_export.py",
        "models/series.py",
        "services/derived.py",
        "services/player_history.py",
        "services/player_series.py",
        "services/season_import.py",
    }
    root = Path(app_package.__file__ or "").parent
    found = {
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if re.search(r"player[12]_off_race", path.read_text())
    }
    assert found == allowed
