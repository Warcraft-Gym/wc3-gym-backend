"""A FOML season run end to end through the API.

FOML is a solo league inside the gym: one event, two divisions cut from MMR,
a round robin where every entrant plays two series a round, then the top four
of each division in a single elimination bracket. Every division runs the
whole event on its own and the two never meet.

Every step is the HTTP call an admin or a member makes, so the assertions read
the shapes the run page draws rather than the rows the engine writes.
"""

from collections.abc import Callable
from itertools import combinations
from typing import Any

from httpx2 import Client

from app.core.db import Session
from app.models.base import ident
from app.models.enums import Race
from app.models.user import User
from app.models.w3c_stats import W3CStats
from tests.seed import active
from tests.test_events import phase
from tests.test_stage_engine import generate, score, stage_series

type Member = Callable[..., dict[str, str]]

# Sixteen signups cut into two bands of eight
FIELD = 16
BAND = 8


def enrol(number: int) -> int:
    """One gym member with a Discord id and a Human rating; number 1 is strongest."""
    with Session.begin() as session:
        user = User(
            name=f"F{number}",
            battle_tags=active(f"F{number}#{number:04d}"),
            discordTag=f"f{number}",
            discordId=str(number),
            race=Race.HU,
        )
        session.add(user)
        session.flush()
        session.add(
            W3CStats(
                user_id=ident(user),
                race=Race.HU,
                wc3_season=23,
                games=200,
                mmr=2400 - number * 50,
            )
        )
        return ident(user)


def open_the_season(
    client: Client, headers: dict[str, str], member: Member
) -> tuple[int, list[int]]:
    """FOML and its fourth season, with sixteen members signed up."""
    league = client.post(
        "/leagues",
        json={
            "name": "Fountain of Manner League",
            "short_name": "FOML",
            "kind": "custom",
            "entrant_kind": "solo",
        },
        headers=headers,
    )
    assert league.status_code == 201, league.text
    created = client.post(
        "/events",
        json={
            "name": "FOML Season 4",
            "kind": "cup",
            "league_id": league.json()["id"],
            "signup_policy": "members",
            "series_per_round": 2,
            "stages": [
                {
                    "name": "Group stage",
                    "format": "round_robin",
                    "best_of": 3,
                    "series_per_entrant_per_round": 2,
                    "advance_count": 4,
                },
                {"name": "Playoffs", "format": "single_elimination", "best_of": 3},
            ],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["league_short_name"] == "FOML"
    assert body["signup_policy"] == "members"
    assert body["entrant_kind"] == "solo"
    assert [
        (row["format"], row["best_of"], row["series_per_entrant_per_round"])
        for row in body["stages"]
    ] == [("round_robin", 3, 2), ("single_elimination", 3, 1)]
    assert body["stages"][0]["advance_count"] == 4

    event = body["id"]
    for number in range(1, FIELD + 1):
        enrol(number)
        entered = client.post(
            f"/events/{event}/entrants",
            json={"race": "HU"},
            headers=member(str(number)),
        )
        assert entered.status_code == 201, entered.text
    assert client.get(f"/events/{event}").json()["entrant_count"] == FIELD
    return event, [stage["id"] for stage in body["stages"]]


def cut_and_seed(
    client: Client, headers: dict[str, str], event: int, stage: int
) -> list[dict[str, Any]]:
    """Two divisions cut from MMR, seeded from MMR inside each, then locked."""
    bands = client.put(
        f"/events/{event}/divisions",
        json=[{"name": "Pro", "size": BAND}, {"name": "Open"}],
        headers=headers,
    )
    assert bands.status_code == 200, bands.text
    assigned = client.post(f"/events/{event}/divisions/assign", headers=headers)
    assert assigned.status_code == 200, assigned.text
    assert [row["entrant_count"] for row in assigned.json()["divisions"]] == [
        BAND,
        BAND,
    ]

    seeded = client.put(
        f"/events/{event}/stages/{stage}/seeds",
        json={"source": "mmr"},
        headers=headers,
    )
    assert seeded.status_code == 200, seeded.text
    rows = seeded.json()
    assert sorted(row["seed"] for row in rows) == sorted(list(range(1, BAND + 1)) * 2)
    assert {row["seed_source"] for row in rows} == {"mmr"}

    locked = client.post(f"/events/{event}/stages/{stage}/seeds/lock", headers=headers)
    assert locked.status_code == 200, locked.text
    assert locked.json()["seeds_locked_at"] is not None
    return rows


def seeds_of(entrants: list[dict[str, Any]]) -> dict[int, int]:
    """Each player against the seed he carries inside his own division."""
    return {
        row["user"]["id"]: row["seed"] for row in entrants if row["seed"] is not None
    }


def play(
    client: Client,
    headers: dict[str, str],
    event: int,
    stage: int,
    seeds: dict[int, int],
    walkover: bool = False,
) -> None:
    """The higher seed takes 2-0 every series that stands with both its sides.

    With `walkover` the first of them is given rather than played, which is the
    other way an admin ends a series.
    """
    given = walkover
    for row in stage_series(client, event, stage)["series"]:
        if row["player1_score"] is not None:
            continue
        if row["player1_id"] is None or row["player2_id"] is None:
            continue
        first = seeds[row["player1_id"]] < seeds[row["player2_id"]]
        if given:
            given = False
            answer = client.put(
                f"/series/{row['id']}/result-kind",
                json={"result_kind": "walkover", "winner": 1 if first else 2},
                headers=headers,
            )
            assert answer.status_code == 200, answer.text
            assert answer.json()["player1_score"] == (2 if first else 0)
        else:
            answer = score(client, headers, row["id"], *((2, 0) if first else (0, 2)))
            assert answer.status_code == 200, answer.text


def winner_of(row: dict[str, Any]) -> int:
    """The player the series sends on, read off the score the API answers."""
    first = row["player1_score"] > row["player2_score"]
    return row["player1_id"] if first else row["player2_id"]


def test_a_foml_stage_pairs_every_entrant_twice_a_round_in_both_divisions(
    client: Client, auth_headers: dict[str, str], member: Member
) -> None:
    """Eight entrants cover their seven opponents in four rounds: three rounds
    of eight series and a short one of four, in each division on its own."""
    event, (stage, _) = open_the_season(client, auth_headers, member)
    entrants = cut_and_seed(client, auth_headers, event, stage)

    assert generate(client, auth_headers, event, stage) == {"series": 56, "rounds": 4}

    body = stage_series(client, event, stage)
    assert [(row["number"], row["name"]) for row in body["rounds"]] == [
        (number, f"Round {number}") for number in range(1, 5)
    ]
    bands = sorted({row["division_id"] for row in entrants})
    assert len(bands) == 2 and None not in bands
    for band in bands:
        field = {row["user"]["id"] for row in entrants if row["division_id"] == band}
        rows = [row for row in body["series"] if row["division_id"] == band]
        assert len(rows) == 28
        pairs = {frozenset((row["player1_id"], row["player2_id"])) for row in rows}
        assert pairs == {frozenset(pair) for pair in combinations(field, 2)}
        for number in (1, 2, 3):
            sides = [
                side
                for row in rows
                if row["round_id"] == body["rounds"][number - 1]["id"]
                for side in (row["player1_id"], row["player2_id"])
            ]
            # Two series an entrant, so every player stands in the round twice
            assert sorted(sides) == sorted(list(field) * 2)
        last = [row for row in rows if row["round_id"] == body["rounds"][3]["id"]]
        assert len(last) == 4


def test_the_run_page_reads_the_rounds_the_sequences_and_no_feeders(
    client: Client, auth_headers: dict[str, str], member: Member
) -> None:
    """A round robin box takes its sides from the seeds, so nothing feeds it,
    and the sequences count from one inside every division and round."""
    event, (stage, _) = open_the_season(client, auth_headers, member)
    entrants = cut_and_seed(client, auth_headers, event, stage)
    generate(client, auth_headers, event, stage)

    body = stage_series(client, event, stage)

    assert len(body["series"]) == 56
    numbers = {row["id"]: row["number"] for row in body["rounds"]}
    for band in sorted({row["division_id"] for row in entrants}):
        places: dict[int, list[int]] = {}
        for row in body["series"]:
            if row["division_id"] == band:
                places.setdefault(numbers[row["round_id"]], []).append(row["sequence"])
        assert {number: sorted(seq) for number, seq in places.items()} == {
            1: list(range(1, 9)),
            2: list(range(1, 9)),
            3: list(range(1, 9)),
            4: list(range(1, 5)),
        }
    for row in body["series"]:
        assert row["slot1_from_series_id"] is None
        assert row["slot2_from_series_id"] is None
        assert (row["slot1_takes_loser"], row["slot2_takes_loser"]) == (False, False)
        assert row["result_kind"] == "played"
        assert row["side_size"] == 1
        assert row["pick_rule"] is None
        # A stage series hangs off its round, not off a fixture
        assert row["match"] is None


def test_the_season_plays_out_to_one_winner_in_each_division(
    client: Client, auth_headers: dict[str, str], member: Member
) -> None:
    """The whole run: the table, the top four through, the bracket, a correction
    that moves the final's side, the winners, and the final reopened."""
    event, (first, second) = open_the_season(client, auth_headers, member)
    entrants = cut_and_seed(client, auth_headers, event, first)
    seeds = seeds_of(entrants)
    generate(client, auth_headers, event, first)

    play(client, auth_headers, event, first, seeds, walkover=True)

    tables = client.get(f"/events/{event}/stages/{first}/standings").json()
    assert [table["division_name"] for table in tables] == ["Pro", "Open"]
    for table in tables:
        rows = table["rows"]
        assert [row["position"] for row in rows] == list(range(1, 9))
        # The higher seed took every series, so the table reads in seed order
        assert [seeds[row["user_id"]] for row in rows] == list(range(1, 9))
        assert [row["points"] for row in rows] == [7, 6, 5, 4, 3, 2, 1, 0]
        assert (rows[0]["played"], rows[0]["won"]) == (7, 7)

    moved = client.post(f"/events/{event}/stages/{first}/advance", headers=auth_headers)
    assert moved.status_code == 200, moved.text
    assert moved.json() == {"seeded": 8}
    carried = {
        row["user"]["id"]: (row["seed"], row["seed_source"])
        for row in client.get(f"/events/{event}/entrants").json()
        if row["seed"] is not None
    }
    # The engine's advance is what seeds a stage from the one before it
    assert {source for _, source in carried.values()} == {"previous_stage"}
    assert sorted(seed for seed, _ in carried.values()) == sorted([1, 2, 3, 4] * 2)
    assert sorted(seeds[player] for player in carried) == sorted([1, 2, 3, 4] * 2)

    assert generate(client, auth_headers, event, second) == {"series": 6, "rounds": 2}
    body = stage_series(client, event, second)
    assert [(row["number"], row["name"]) for row in body["rounds"]] == [
        (5, "Semifinals"),
        (6, "Final"),
    ]
    bands = sorted({row["division_id"] for row in body["series"]})
    for band in bands:
        rows = [row for row in body["series"] if row["division_id"] == band]
        assert len(rows) == 3
        semis, final = rows[:2], rows[2]
        assert all(row["slot1_from_series_id"] is None for row in semis)
        assert final["slot1_from_series_id"] == semis[0]["id"]
        assert final["slot2_from_series_id"] == semis[1]["id"]
        assert (final["player1_id"], final["player2_id"]) == (None, None)

    top = {
        row["user"]["id"]: row["seed"]
        for row in client.get(f"/events/{event}/entrants").json()
        if row["seed"] is not None
    }
    play(client, auth_headers, event, second, top)
    rows = stage_series(client, event, second)["series"]
    finals = [row for row in rows if row["round_id"] == body["rounds"][1]["id"]]
    assert len(finals) == 2
    assert all(row["player1_id"] is not None for row in finals)

    # The admin saved one semifinal backwards and corrects it in place
    semi = next(row for row in rows if row["round_id"] == body["rounds"][0]["id"])
    final = next(row for row in finals if row["division_id"] == semi["division_id"])
    assert final["player1_id"] == winner_of(semi)
    corrected = score(client, auth_headers, semi["id"], 0, 2)
    assert corrected.status_code == 200, corrected.text
    after = next(
        row
        for row in stage_series(client, event, second)["series"]
        if row["id"] == final["id"]
    )
    assert after["player1_id"] == semi["player2_id"]
    assert after["player1_id"] != final["player1_id"]

    play(client, auth_headers, event, second, top)

    played = stage_series(client, event, second)["series"]
    finals = [row for row in played if row["round_id"] == body["rounds"][1]["id"]]
    tables = client.get(f"/events/{event}/stages/{second}/standings").json()
    assert len(tables) == 2
    for table in tables:
        won = next(row for row in finals if row["division_id"] == table["division_id"])
        assert table["rows"][0]["user_id"] == winner_of(won)

    last = finals[0]
    cleared = client.put(
        f"/series/{last['id']}?force=true",
        json={"player1_score": None, "player2_score": None},
        headers=auth_headers,
    )
    assert cleared.status_code == 200, cleared.text
    reopened = next(
        row
        for row in stage_series(client, event, second)["series"]
        if row["id"] == last["id"]
    )
    assert (reopened["player1_score"], reopened["player2_score"]) == (None, None)
    assert reopened["result_kind"] == "played"
    # The final keeps the two the semifinals sent it; only what it fed is cleared
    assert (reopened["player1_id"], reopened["player2_id"]) == (
        last["player1_id"],
        last["player2_id"],
    )


def test_the_phase_of_a_generated_event_reads_running_then_finished(
    client: Client, auth_headers: dict[str, str], member: Member
) -> None:
    """The phase counts an event's series through their rounds
    (series_counts_by_event, app/models/season.py:202), so a generated series,
    which names a round and no fixture, counts like a GNL one: the event reads
    running on the first result and finished on the last.
    """
    event, (first, second) = open_the_season(client, auth_headers, member)
    assert phase(client, event) == "signups_open"

    entrants = cut_and_seed(client, auth_headers, event, first)
    seeds = seeds_of(entrants)
    closed = client.put(
        f"/events/{event}", json={"signups_open": False}, headers=auth_headers
    )
    assert closed.status_code == 200, closed.text
    # No round exists before the stage is generated, so there is nothing to check into
    assert phase(client, event) == "seeded"

    generate(client, auth_headers, event, first)
    # The generated rounds carry dates, so the first one's check-in window stands
    assert phase(client, event) == "checkin"

    one = stage_series(client, event, first)["series"][0]
    assert score(client, auth_headers, one["id"], 2, 0).status_code == 200
    assert phase(client, event) == "running"

    play(client, auth_headers, event, first, seeds)
    moved = client.post(f"/events/{event}/stages/{first}/advance", headers=auth_headers)
    assert moved.status_code == 200, moved.text
    generate(client, auth_headers, event, second)
    assert phase(client, event) == "running"

    top = {
        row["user"]["id"]: row["seed"]
        for row in client.get(f"/events/{event}/entrants").json()
        if row["seed"] is not None
    }
    # The semifinals first, then the finals they feed
    play(client, auth_headers, event, second, top)
    play(client, auth_headers, event, second, top)

    assert all(
        row["player1_score"] is not None
        for stage in (first, second)
        for row in stage_series(client, event, stage)["series"]
    )
    assert phase(client, event) == "finished"
