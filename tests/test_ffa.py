"""A free for all run as lobbies with places, through the routes an admin drives.

Bench row 19: sixteen entrants play an FFA bracket of lobbies of four, the top
two of every lobby play on until one final lobby is left, and the four the
stage sends through play an FFA league of three series paying 4, 3, 2, 1.
"""

from typing import Any

from httpx2 import Client

from app.core.db import Session
from app.models.base import ident
from app.models.enums import EventKind, Race, StageFormat
from app.models.event_entrant import EventEntrant
from app.models.event_stage import EventStage
from app.models.season import Season
from tests.test_stage_engine import generate, players, players_of

# What every lobby of this event pays its places, best place first
POINTS = "4,3,2,1"


def ffa(count: int = 16) -> tuple[int, int, int]:
    """An event whose bracket of lobbies feeds a league final of one lobby."""
    ids = players(count)
    with Session.begin() as session:
        event = Season(
            name="SMF FFA", kind=EventKind.cup, series_per_round=1, published=True
        )
        session.add(event)
        session.flush()
        stages = [
            EventStage(
                event_id=ident(event),
                position=1,
                format=StageFormat.ffa,
                lobby_size=4,
                group_advance=2,
                points_by_place=POINTS,
                advance_count=4,
            ),
            EventStage(
                event_id=ident(event),
                position=2,
                format=StageFormat.ffa,
                lobby_size=4,
                swiss_rounds=3,
                points_by_place=POINTS,
            ),
        ]
        session.add_all(stages)
        session.flush()
        for seed, user_id in enumerate(ids, start=1):
            session.add(
                EventEntrant(
                    event_id=ident(event), user_id=user_id, race=Race.HU, seed=seed
                )
            )
        session.flush()
        return ident(event), ident(stages[0]), ident(stages[1])


def seeds_of(event: int) -> dict[int, int]:
    """The seed each player stands on, keyed by the player."""
    return {user: seed for seed, user in enumerate(players_of(event), start=1)}


def lobbies(
    client: Client, event: int, stage: int, name: str | None = None
) -> list[dict[str, Any]]:
    """Every lobby of the stage, or of one round of it, in play order."""
    data = client.get(f"/events/{event}/stages/{stage}/series").json()
    rounds = {row["id"]: row["name"] for row in data["rounds"]}
    return [
        row
        for row in data["series"]
        if name is None or rounds.get(row["round_id"]) == name
    ]


def seated(lobby: dict[str, Any], seeds: dict[int, int]) -> list[int]:
    """The seed sitting in every seat of the lobby, 0 for a seat still open."""
    return [seeds.get(side["user_id"], 0) for side in lobby["sides"]]


def play(
    client: Client, headers: dict[str, str], lobby: dict[str, Any], order: list[int]
) -> Any:  # noqa: ANN401
    """Place the seats of one lobby, `order` naming the seats best place first."""
    return client.put(
        f"/series/{lobby['id']}/places",
        json={
            "places": [
                {"side_no": side_no, "place": place}
                for place, side_no in enumerate(order, start=1)
            ]
        },
        headers=headers,
    )


def by_seed(lobby: dict[str, Any], seeds: dict[int, int]) -> list[int]:
    """The seats of one lobby, the best seed first: the order a lobby ends in
    when every player finishes where his seed says."""
    return [
        side["side_no"]
        for side in sorted(lobby["sides"], key=lambda side: seeds[side["user_id"]])
    ]


def settle(client: Client, headers: dict[str, str], event: int, stage: int) -> None:
    """Place every open lobby of the stage: the best seed of a lobby wins it."""
    seeds = seeds_of(event)
    for lobby in lobbies(client, event, stage):
        if lobby["player1_score"] is not None or 0 in seated(lobby, seeds):
            continue
        done = play(client, headers, lobby, by_seed(lobby, seeds))
        assert done.status_code == 200, done.text


def table(client: Client, event: int, stage: int) -> list[dict[str, Any]]:
    """One division's table, best place first."""
    return client.get(f"/events/{event}/stages/{stage}/standings").json()[0]["rows"]


def test_sixteen_entrants_play_lobbies_of_four_down_to_one_final_lobby(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Four lobbies feed two, and the two feed the final lobby of four."""
    event, bracket, _ = ffa()
    assert generate(client, auth_headers, event, bracket) == {"series": 7, "rounds": 3}
    seeds = seeds_of(event)
    first = lobbies(client, event, bracket, "Round 1")
    assert [seated(row, seeds) for row in first] == [
        [1, 8, 9, 16],
        [2, 7, 10, 15],
        [3, 6, 11, 14],
        [4, 5, 12, 13],
    ]
    # A lobby names no player of its own; its seats do
    assert [row["player1_id"] for row in first] == [None] * 4
    # The rounds below open empty and wait for the places above them
    later = lobbies(client, event, bracket, "Round 2")
    assert len(later) == 2
    assert [side["user_id"] for row in later for side in row["sides"]] == [None] * 8
    assert len(lobbies(client, event, bracket, "Final")) == 1


def test_the_top_two_places_of_every_lobby_fill_the_round_below(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, bracket, _ = ffa()
    generate(client, auth_headers, event, bracket)
    seeds = seeds_of(event)
    first = lobbies(client, event, bracket, "Round 1")
    # The round below fills only once every lobby above it carries its places
    assert (
        play(client, auth_headers, first[0], by_seed(first[0], seeds)).status_code
        == 200
    )
    assert seated(lobbies(client, event, bracket, "Round 2")[0], seeds) == [0, 0, 0, 0]
    for lobby in first[1:]:
        assert (
            play(client, auth_headers, lobby, by_seed(lobby, seeds)).status_code == 200
        )
    # Every lobby winner is seeded above every runner-up, then the snake deals
    assert [
        seated(row, seeds) for row in lobbies(client, event, bracket, "Round 2")
    ] == [
        [1, 4, 8, 5],
        [2, 3, 7, 6],
    ]
    settle(client, auth_headers, event, bracket)
    assert seated(lobbies(client, event, bracket, "Final")[0], seeds) == [1, 2, 4, 3]


def test_the_stage_table_sums_the_place_points_and_advances_the_top_four(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, bracket, league = ffa()
    generate(client, auth_headers, event, bracket)
    for _ in range(3):
        settle(client, auth_headers, event, bracket)
    seeds = seeds_of(event)
    rows = table(client, event, bracket)
    # Seed 1 took three lobbies at four points each; the field ranks behind him
    assert [(seeds[row["user_id"]], row["points"]) for row in rows[:4]] == [
        (1, 12),
        (2, 11),
        (3, 9),
        (4, 8),
    ]
    assert (rows[0]["played"], rows[0]["won"]) == (3, 3)
    moved = client.post(
        f"/events/{event}/stages/{bracket}/advance", headers=auth_headers
    )
    assert moved.status_code == 200, moved.text
    assert moved.json() == {"seeded": 4}
    assert generate(client, auth_headers, event, league) == {"series": 3, "rounds": 1}


def test_the_league_final_plays_three_series_and_the_points_leader_wins(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """One lobby of four plays three series; the leader on points is not the
    player that took the first of them."""
    event, bracket, league = ffa()
    generate(client, auth_headers, event, bracket)
    for _ in range(3):
        settle(client, auth_headers, event, bracket)
    # The advance reseeds the event, so the bracket's own seeds are read first
    seeds = seeds_of(event)
    client.post(f"/events/{event}/stages/{bracket}/advance", headers=auth_headers)
    generate(client, auth_headers, event, league)
    rows = lobbies(client, event, league)
    assert len(rows) == 3
    # One lobby plays every series of the stage, so the four seats never change
    assert [seated(row, seeds) for row in rows] == [[1, 2, 3, 4]] * 3
    for lobby, order in zip(
        rows, ([1, 2, 3, 4], [4, 3, 2, 1], [2, 1, 4, 3]), strict=True
    ):
        assert play(client, auth_headers, lobby, order).status_code == 200
    assert [
        (seeds[row["user_id"]], row["points"]) for row in table(client, event, league)
    ] == [
        (2, 9),
        (1, 8),
        (4, 7),
        (3, 6),
    ]


def test_an_organiser_moves_an_entrant_between_lobbies_before_the_round(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, bracket, _ = ffa()
    generate(client, auth_headers, event, bracket)
    seeds = seeds_of(event)
    first, second = lobbies(client, event, bracket, "Round 1")[:2]
    swapped = [side["entrant_id"] for side in first["sides"]]
    swapped[-1] = second["sides"][-1]["entrant_id"]
    moved = client.put(
        f"/series/{first['id']}/sides",
        json={"entrant_ids": swapped},
        headers=auth_headers,
    )
    assert moved.status_code == 200, moved.text
    assert [seeds[side["user_id"]] for side in moved.json()["sides"]] == [1, 8, 9, 15]
    assert seated(lobbies(client, event, bracket, "Round 1")[0], seeds) == [1, 8, 9, 15]


def test_a_played_lobby_keeps_its_seats_and_a_two_sided_series_takes_none(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, bracket, _ = ffa()
    generate(client, auth_headers, event, bracket)
    seeds = seeds_of(event)
    lobby = lobbies(client, event, bracket, "Round 1")[0]
    assert play(client, auth_headers, lobby, by_seed(lobby, seeds)).status_code == 200
    settled = client.put(
        f"/series/{lobby['id']}/sides",
        json={"entrant_ids": [side["entrant_id"] for side in lobby["sides"]]},
        headers=auth_headers,
    )
    assert settled.status_code == 400
    assert "settled" in settled.text
    short = client.put(
        f"/series/{lobby['id']}/places",
        json={"places": [{"side_no": 1, "place": 1}, {"side_no": 9, "place": 2}]},
        headers=auth_headers,
    )
    assert short.status_code == 400
    assert "seats no side 9" in short.text


def test_a_reader_cannot_place_a_lobby(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, bracket, _ = ffa()
    generate(client, auth_headers, event, bracket)
    lobby = lobbies(client, event, bracket, "Round 1")[0]
    assert (
        client.put(f"/series/{lobby['id']}/places", json={"places": []}).status_code
        == 401
    )
    assert (
        client.put(f"/series/{lobby['id']}/sides", json={"entrant_ids": []}).status_code
        == 401
    )
