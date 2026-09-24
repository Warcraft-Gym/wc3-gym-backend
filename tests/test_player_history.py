"""GET /player-history: the seasons a player took part in and everyone they met.

Nothing here is stored. The fixture adds a second season on top of the seeded
one, so the tests can see a record add up across seasons, a team finish
second, and the current season read as running.

Season 1 (seeded): P1 beats P3 2-1, so team Alpha takes 2 points and Beta 1,
and Alpha finishes first of two.
Season 2 (this module): P1 loses 0-2 to P3 and P2 loses 1-2 to P4 on playday 1,
P1 beats P4 2-0 on playday 2 and their series against P3 is not played yet.
Alpha takes 4 points and Beta 5, so Alpha finishes second of two.
"""

from collections.abc import Callable
from datetime import date, datetime
from typing import Any

import pytest
from httpx2 import Client


def _second_season(seeded: dict[str, Any]) -> dict[str, Any]:
    """The seeded season, plus a second one the same two teams played."""
    from app.core.db import Session
    from app.models.base import ident
    from app.models.match import Match
    from app.models.relationships import DBUserSeasonSignup
    from app.models.season import Season
    from app.models.series import Series
    from app.models.settings import Settings
    from app.models.team_season import DBTeamSeason
    from app.models.user import User
    from app.models.user_team_season import DBUserTeamSeason

    p1, p2, p3, p4 = seeded["player_ids"]
    with Session() as session:
        season = Season(
            name="Season 2",
            series_per_round=2,
            start_date=date(2026, 3, 5),
            end_date=date(2026, 4, 27),
        )
        session.add(season)
        session.flush()
        # A rostered player registers for the season, so a meeting names his race
        rostered = [session.get(User, user_id) for user_id in (p1, p2, p3, p4)]
        session.add_all(
            DBUserSeasonSignup(user_id=ident(one), season_id=season_id, race=one.race)
            for season_id in (seeded["season_id"], ident(season))
            for one in rostered
            if one
        )
        session.add_all(
            [
                DBTeamSeason(team_id=seeded["team_a_id"], season_id=ident(season)),
                DBTeamSeason(team_id=seeded["team_b_id"], season_id=ident(season)),
                Settings(key="current_gnl_season", value=str(ident(season))),
            ]
            + [
                DBUserTeamSeason(
                    user_id=user_id,
                    team_id=team_id,
                    season_id=ident(season),
                )
                for user_id, team_id in (
                    (p1, seeded["team_a_id"]),
                    (p2, seeded["team_a_id"]),
                    (p3, seeded["team_b_id"]),
                    (p4, seeded["team_b_id"]),
                )
            ]
        )
        matches = [
            Match(
                team1_id=seeded["team_a_id"],
                team2_id=seeded["team_b_id"],
                season_id=ident(season),
                playday=playday,
            )
            for playday in (1, 2)
        ]
        session.add_all(matches)
        session.flush()
        session.add_all(
            [
                Series(
                    match_id=ident(matches[0]),
                    date_time=datetime(2026, 3, 7, 19, 0),
                    player1_id=p1,
                    player2_id=p3,
                    player1_score=0,
                    player2_score=2,
                    host_player_id=p1,
                ),
                Series(
                    match_id=ident(matches[0]),
                    player1_id=p2,
                    player2_id=p4,
                    player1_score=1,
                    player2_score=2,
                    host_player_id=p2,
                ),
                Series(
                    match_id=ident(matches[1]),
                    date_time=datetime(2026, 3, 14, 19, 0),
                    player1_id=p1,
                    player2_id=p4,
                    player1_score=2,
                    player2_score=0,
                    host_player_id=p1,
                ),
                # not played yet, so it pays no record and shows in no meeting
                Series(
                    match_id=ident(matches[1]),
                    player1_id=p1,
                    player2_id=p3,
                    host_player_id=p1,
                ),
            ]
        )
        session.commit()
        return seeded | {"season2_id": ident(season)}


@pytest.fixture
def two_seasons(seeded: dict[str, Any]) -> dict[str, Any]:
    return _second_season(seeded)


def test_events_carry_the_team_and_the_record_of_every_season(
    client: Client, two_seasons: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    """P1 stood in both seasons for Alpha, one series in the first and two in
    the second, and every row names the team's logo."""
    from app.core.db import Session
    from app.models.team import Team

    with Session.begin() as session:
        Team.update(session, two_seasons["team_a_id"], icon_url="teams/alpha.png")

    resp = client.get("/player-history", headers=member("1"))

    assert resp.status_code == 200, resp.text
    events = resp.json()["events"]
    assert [event["season_name"] for event in events] == ["Season 2", "Season 1"]
    assert all(event["team_name"] == "Alpha" for event in events)
    assert all(event["team_icon_url"] == "teams/alpha.png" for event in events)
    assert [(event["played"], event["won"], event["lost"]) for event in events] == [
        (2, 1, 1),
        (1, 1, 0),
    ]
    # A player with GNL history alone reads the one kind
    assert {event["kind"] for event in events} == {"gnl"}


def test_events_carry_the_finish_the_standings_derive(
    client: Client, two_seasons: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    """Alpha took the first season on points and lost the second."""
    resp = client.get("/player-history", headers=member("1"))

    events = resp.json()["events"]
    assert [(event["place"], event["team_count"]) for event in events] == [
        (2, 2),
        (1, 2),
    ]


def test_the_current_season_reads_as_running(
    client: Client, two_seasons: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    resp = client.get("/player-history", headers=member("1"))

    events = resp.json()["events"]
    assert [event["running"] for event in events] == [True, False]


def test_a_season_nobody_scored_in_has_no_finish(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    """The seeded win is wiped, so no team stands anywhere and no place is invented."""
    from app.core.db import Session
    from app.models.series import Series

    with Session() as session:
        series = session.get(Series, seeded["series_played_id"])
        assert series is not None
        series.player1_score = None
        series.player2_score = None
        session.commit()

    resp = client.get("/player-history", headers=member("1"))

    event = resp.json()["events"][0]
    assert (event["place"], event["team_count"]) == (None, None)
    assert (event["played"], event["won"], event["lost"]) == (0, 0, 0)


def test_head_to_head_adds_a_player_up_over_every_season(
    client: Client, two_seasons: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    """P1 met P3 in both seasons and P4 once, so P3 sorts first."""
    resp = client.get("/player-history", headers=member("1"))

    opponents = resp.json()["opponents"]
    assert [one["name"] for one in opponents] == ["P3", "P4"]
    p3, p4 = opponents
    assert (p3["played"], p3["won"], p3["lost"]) == (2, 1, 1)
    assert (p4["played"], p4["won"], p4["lost"]) == (1, 1, 0)
    assert (p3["race"], p3["country"]) == ("NE", "FR")
    assert (p3["last_season_name"], p3["last_playday"]) == ("Season 2", 1)


def test_meetings_read_newest_first_and_carry_both_scores(
    client: Client, two_seasons: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    resp = client.get("/player-history", headers=member("1"))

    meetings = resp.json()["opponents"][0]["meetings"]
    assert [one["season_name"] for one in meetings] == ["Season 2", "Season 1"]
    assert [(one["my_score"], one["their_score"]) for one in meetings] == [
        (0, 2),
        (2, 1),
    ]
    assert meetings[0]["date_time"].startswith("2026-03-07")


def test_a_meeting_carries_the_fixed_map_and_the_picks(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    """The seeded series gets a fixed map and one veto pick; bans stay out."""
    from app.core.db import Session
    from app.models.base import ident
    from app.models.map import Map
    from app.models.series import Series
    from app.models.series_veto_step import DBSeriesVetoStep

    with Session() as session:
        picked = Map(name="Echo Isles", shortname="EI")
        banned = Map(name="Turtle Rock", shortname="TR")
        session.add_all([picked, banned])
        session.flush()
        series = session.get(Series, seeded["series_played_id"])
        assert series is not None
        series.match.fixed_map_id = seeded["map_id"]
        session.add_all(
            [
                DBSeriesVetoStep(
                    series_id=ident(series),
                    step_no=1,
                    side="A",
                    action="ban",
                    map_id=ident(banned),
                ),
                DBSeriesVetoStep(
                    series_id=ident(series),
                    step_no=2,
                    side="B",
                    action="pick",
                    map_id=ident(picked),
                ),
            ]
        )
        session.commit()

    resp = client.get("/player-history", headers=member("1"))

    meeting = resp.json()["opponents"][0]["meetings"][0]
    assert meeting["maps"] == ["Concealed Hill", "Echo Isles"]


def test_a_player_with_no_history_answers_empty_lists(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    from app.core.db import Session
    from app.models.enums import Race
    from app.models.user import User

    with Session() as session:
        session.add(
            User(
                name="P9",
                battleTag="P9#9999",
                discordTag="p9",
                discordId="9",
                race=Race.HU,
            )
        )
        session.commit()

    resp = client.get("/player-history", headers=member("9"))

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"events": [], "opponents": [], "captain_of": []}


def test_the_answer_costs_eleven_statements_however_long_the_career(
    seeded: dict[str, Any],
) -> None:
    """HARD GATE: neither block loops. One season and one opponent cost what
    two seasons and two opponents cost. The ninth statement is the entrant
    read that carries the events outside GNL, the tenth the GNL signup read,
    the eleventh the captain seats."""
    from app.services.player_history import history
    from tests.test_query_budget import count_statements

    with count_statements() as one_season:
        history(seeded["player_ids"][0])
    _second_season(seeded)
    with count_statements() as two_seasons:
        history(seeded["player_ids"][0])

    assert one_season[0] == two_seasons[0] == 11


def test_an_unknown_player_answers_404(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    resp = client.get("/player-history", headers=member("404"))

    assert resp.status_code == 404, resp.text
    assert resp.json() == {"error": "player_not_found"}


def test_anyone_reads_another_player_history_by_id(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    """The page of a player is public, so the same answer needs no session."""
    p1 = seeded["player_ids"][0]

    public = client.get(f"/users/{p1}/history")
    own = client.get("/player-history", headers=member("1"))

    assert public.status_code == 200, public.text
    assert public.json() == own.json()


def test_the_history_of_an_unknown_id_is_empty(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The page reads the player first, so the history route needs no second check."""
    resp = client.get("/users/404404/history")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"events": [], "opponents": [], "captain_of": []}


def _signup_race(season_id: int, user_id: int, race: object) -> None:
    """Set the race one player signed one season up on."""
    from sqlmodel import col, select

    from app.core.db import Session
    from app.models.relationships import DBUserSeasonSignup

    with Session() as session:
        signup = session.execute(
            select(DBUserSeasonSignup).where(
                col(DBUserSeasonSignup.user_id) == user_id,
                col(DBUserSeasonSignup.season_id) == season_id,
            )
        ).scalar_one()
        signup.race = race
        session.commit()


def test_a_meeting_carries_the_race_each_side_signed_that_season_up_on(
    client: Client, two_seasons: dict[str, Any]
) -> None:
    """P1 met P3 in both seasons and signed the second one up as undead, so the
    two meetings answer a different my_race."""
    from app.models.enums import Race

    p1, _, p3, _ = two_seasons["player_ids"]
    _signup_race(two_seasons["season2_id"], p1, Race.UD)

    meetings = client.get(f"/users/{p1}/history").json()["opponents"][0]["meetings"]

    assert [one["season_name"] for one in meetings] == ["Season 2", "Season 1"]
    assert [one["my_race"] for one in meetings] == ["UD", "HU"]
    assert [one["their_race"] for one in meetings] == ["NE", "NE"]
    # The same series read from the other side answers the two races swapped
    mirror = client.get(f"/users/{p3}/history").json()["opponents"]
    against_p1 = next(one for one in mirror if one["id"] == p1)
    assert [one["my_race"] for one in against_p1["meetings"]] == ["NE", "NE"]
    assert [one["their_race"] for one in against_p1["meetings"]] == ["UD", "HU"]


def test_an_off_race_series_answers_the_race_the_side_reported(
    client: Client, two_seasons: dict[str, Any]
) -> None:
    """The off race of a series beats the race the side signed the season up on."""
    from app.core.db import Session
    from app.models.enums import Race
    from app.models.series import Series

    p1 = two_seasons["player_ids"][0]
    with Session() as session:
        series = session.get(Series, two_seasons["series_played_id"])
        assert series is not None
        series.player1_off_race = Race.OC
        series.player2_off_race = Race.HU
        session.commit()

    meetings = client.get(f"/users/{p1}/history").json()["opponents"][0]["meetings"]

    assert meetings[1]["season_name"] == "Season 1"
    assert (meetings[1]["my_race"], meetings[1]["their_race"]) == ("OC", "HU")
    # The season 2 meeting reports no off race, so both sides keep their signup
    assert (meetings[0]["my_race"], meetings[0]["their_race"]) == ("HU", "NE")
    # The opponent race stays the newest meeting's race
    assert client.get(f"/users/{p1}/history").json()["opponents"][0]["race"] == "NE"


def test_a_cup_entrant_reads_the_cup_before_a_bracket_exists(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """The entrant row alone puts the event on the page, with an empty record."""
    from tests.test_stage_engine import cup, players_of

    event, _ = cup(4)
    entrant = players_of(event)[0]

    events = client.get(f"/users/{entrant}/history").json()["events"]

    assert [(one["season_name"], one["kind"]) for one in events] == [
        ("Autumn Cup", "cup")
    ]
    assert (events[0]["played"], events[0]["won"], events[0]["lost"]) == (0, 0, 0)
    # A cup entrant stands on no team, so no team finish is invented
    assert (events[0]["team_id"], events[0]["place"]) == (None, None)


def test_a_scored_bracket_series_pays_a_record_and_a_meeting(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """A generated series has no fixture, so the event comes through its round."""
    from tests.test_stage_engine import bracket, cup, generate, score

    event, (stage,) = cup(4)
    generate(client, auth_headers, event, stage)
    semi = bracket(stage)[0]
    winner, loser = semi["sides"]
    assert score(client, auth_headers, semi["id"], 2, 0).status_code == 200

    history = client.get(f"/users/{winner}/history").json()

    row = history["events"][0]
    assert (row["kind"], row["played"], row["won"], row["lost"]) == ("cup", 1, 1, 0)
    opponent = history["opponents"][0]
    assert opponent["id"] == loser
    meeting = opponent["meetings"][0]
    assert (meeting["kind"], meeting["my_score"], meeting["their_score"]) == (
        "cup",
        2,
        0,
    )
    assert meeting["season_name"] == "Autumn Cup"
    # The other side reads the same meeting turned around
    mirror = client.get(f"/users/{loser}/history").json()
    assert mirror["events"][0]["lost"] == 1
    assert mirror["opponents"][0]["meetings"][0]["their_score"] == 2


def test_a_running_cup_reads_as_running(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """No setting pins a cup, so its dates say whether it is on today."""
    from app.core.db import Session
    from app.models.season import Season
    from app.models.types import utcnow
    from tests.test_stage_engine import cup, players_of

    event, _ = cup(4)
    entrant = players_of(event)[0]
    with Session.begin() as session:
        row = session.get(Season, event)
        assert row is not None
        row.start_date = row.end_date = utcnow().date()

    events = client.get(f"/users/{entrant}/history").json()["events"]

    assert events[0]["running"] is True


def test_a_withdrawn_entrant_stands_in_the_cup_no_more(
    client: Client, auth_headers: dict[str, str]
) -> None:
    from sqlmodel import col, select

    from app.core.db import Session
    from app.models.event_entrant import EventEntrant
    from app.models.types import utcnow
    from tests.test_stage_engine import cup, players_of

    event, _ = cup(4)
    entrant = players_of(event)[0]
    with Session.begin() as session:
        row = session.scalars(
            select(EventEntrant).where(col(EventEntrant.user_id) == entrant)
        ).one()
        row.withdrawn_at = utcnow()

    assert client.get(f"/users/{entrant}/history").json()["events"] == []


def test_a_gnl_signup_alone_puts_the_season_on_the_page(
    client: Client, seeded: dict[str, Any]
) -> None:
    """A player signs up, no team drafts him and he plays nothing: the season
    still reads, with the race he signed up on and an empty record."""
    from app.core.db import Session
    from app.models.base import ident
    from app.models.enums import Race
    from app.models.relationships import DBUserSeasonSignup
    from app.models.user import User

    with Session.begin() as session:
        undrafted = User(
            name="P9", battleTag="P9#9999", discordTag="p9", discordId="9", race=Race.HU
        )
        session.add(undrafted)
        session.flush()
        signed_up = ident(undrafted)
        session.add(
            DBUserSeasonSignup(
                user_id=signed_up, season_id=seeded["season_id"], race=Race.UD
            )
        )

    events = client.get(f"/users/{signed_up}/history").json()["events"]

    assert [(one["season_name"], one["kind"]) for one in events] == [
        ("Season 1", "gnl")
    ]
    assert events[0]["signup_race"] == "UD"
    assert (events[0]["played"], events[0]["won"], events[0]["lost"]) == (0, 0, 0)
    # Nobody drafted him, so no team and no finish is invented
    assert (events[0]["team_id"], events[0]["place"]) == (None, None)


def test_a_rostered_player_reads_his_signup_season_once(
    client: Client, two_seasons: dict[str, Any]
) -> None:
    """P1 signed both seasons up and was rostered in both: two rows, not four,
    and each keeps its team and its record."""
    from app.models.enums import Race

    p1 = two_seasons["player_ids"][0]
    _signup_race(two_seasons["season2_id"], p1, Race.UD)

    events = client.get(f"/users/{p1}/history").json()["events"]

    assert [one["season_name"] for one in events] == ["Season 2", "Season 1"]
    assert [one["signup_race"] for one in events] == ["UD", "HU"]
    assert [one["team_name"] for one in events] == ["Alpha", "Alpha"]
    assert [(one["played"], one["won"], one["lost"]) for one in events] == [
        (2, 1, 1),
        (1, 1, 0),
    ]
