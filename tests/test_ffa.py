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
from app.models.relationships import DBMapSeason
from app.models.season import Season
from tests.test_cup_best_of import maps
from tests.test_cup_withdraw import entrant_of, withdraw
from tests.test_stage_engine import generate, players, players_of

# What every lobby of this event pays its places, best place first
POINTS = "4,3,2,1"


def ffa(count: int = 16) -> tuple[int, int, int]:
    """An event whose bracket of lobbies feeds a league final of one lobby."""
    ids = players(count)
    pool = maps(3)
    with Session.begin() as session:
        event = Season(
            name="SMF FFA",
            kind=EventKind.cup,
            series_per_round=1,
            published=True,
            checkin_enabled=False,
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
        # every lobby plays one map of the pool
        session.add_all(
            DBMapSeason(season_id=ident(event), map_id=map_id, position=position)
            for position, map_id in enumerate(pool)
        )
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
        f"/cup-series/{lobby['id']}/places",
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


def move(
    client: Client, headers: dict[str, str], lobby: int, entrant: int, to: int
) -> Any:  # noqa: ANN401
    """Move one entrant from the lobby `lobby` to the lobby `to`."""
    return client.post(
        f"/cup-series/{lobby}/move",
        json={"entrant_id": entrant, "to_series_id": to},
        headers=headers,
    )


def test_an_organiser_moves_an_entrant_between_lobbies_before_the_round(
    client: Client,
    auth_headers: dict[str, str],
    member: Any,  # noqa: ANN401
) -> None:
    event, bracket, _ = ffa()
    generate(client, auth_headers, event, bracket)
    seeds = seeds_of(event)
    first, second = lobbies(client, event, bracket, "Round 1")[:2]
    fifteen = second["sides"][-1]["entrant_id"]
    sixteen = first["sides"][-1]["entrant_id"]
    player = member(discord_of(first["sides"][0]["user_id"]))
    refused = move(client, player, second["id"], fifteen, first["id"])
    assert refused.status_code == 403, refused.text

    moved = move(client, auth_headers, second["id"], fifteen, first["id"])

    assert moved.status_code == 200, moved.text
    # the answer is the lobby left, then the lobby joined
    assert [seated(row, seeds) for row in moved.json()] == [
        [2, 7, 10],
        [1, 8, 9, 16, 15],
    ]
    back = move(client, auth_headers, first["id"], sixteen, second["id"])
    assert back.status_code == 200, back.text
    assert [seated(row, seeds) for row in lobbies(client, event, bracket, "Round 1")][
        :2
    ] == [[1, 8, 9, 15], [2, 7, 10, 16]]


def lobby_of(client: Client, event: int, stage: int, series: int) -> dict[str, Any]:
    """One lobby of the stage, found by its id."""
    return next(row for row in lobbies(client, event, stage) if row["id"] == series)


def test_a_move_refuses_and_leaves_both_lobbies_as_they_were(
    client: Client, auth_headers: dict[str, str]
) -> None:
    from app.models.cup_series import CupSeries
    from app.models.event_division import EventDivision

    event, bracket, _ = ffa()
    generate(client, auth_headers, event, bracket)
    seeds = seeds_of(event)
    first, second, third, fourth = lobbies(client, event, bracket, "Round 1")
    below = lobbies(client, event, bracket, "Round 2")[0]
    assert play(client, auth_headers, fourth, by_seed(fourth, seeds)).status_code == 200
    # the third lobby plays in a division of its own
    with Session.begin() as session:
        division = EventDivision(event_id=event, name="Other", position=1)
        session.add(division)
        session.flush()
        held = session.get(CupSeries, third["id"])
        assert held is not None
        held.division_id = ident(division)
        # a series of two sides in the round seats no lobby
        pair = CupSeries(round_id=first["round_id"])
        session.add(pair)
        session.flush()
        sided = {"id": ident(pair)}
    one, eight = (side["entrant_id"] for side in first["sides"][:2])
    two = second["sides"][0]["entrant_id"]
    withdraw(client, auth_headers, event, eight)
    before = [seated(row, seeds) for row in lobbies(client, event, bracket)]

    for lobby, entrant, to, error in (
        (first, one, below, "Move a player to a lobby of the same round and division"),
        (first, one, third, "Move a player to a lobby of the same round and division"),
        (first, one, fourth, "A lobby that holds places keeps its seats"),
        (
            fourth,
            fourth["sides"][0]["entrant_id"],
            first,
            "A lobby that holds places keeps its seats",
        ),
        (first, two, second, "This entrant sits in no seat of this lobby"),
        (first, one, first, "This entrant sits in that lobby already"),
        (first, eight, second, "A player who left the cup moves to no lobby"),
        (first, one, sided, "Only a lobby seats players to move"),
    ):
        refused = move(client, auth_headers, lobby["id"], entrant, to["id"])
        assert refused.status_code == 400, refused.text
        assert refused.json() == {"error": error}
    assert [seated(row, seeds) for row in lobbies(client, event, bracket)] == before

    # a lobby keeps two seats: the second lobby gives two of its four away
    for side in second["sides"][:2]:
        moved = move(
            client, auth_headers, second["id"], side["entrant_id"], first["id"]
        )
        assert moved.status_code == 200, moved.text
    short = move(
        client,
        auth_headers,
        second["id"],
        second["sides"][2]["entrant_id"],
        first["id"],
    )
    assert short.status_code == 400, short.text
    assert short.json() == {"error": "A lobby keeps two seats or more"}
    assert seated(lobby_of(client, event, bracket, second["id"]), seeds) == [10, 15]


def test_the_sides_of_a_lobby_refuse_an_entrant_seated_in_another_of_its_round(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, bracket, _ = ffa()
    generate(client, auth_headers, event, bracket)
    seeds = seeds_of(event)
    first, second = lobbies(client, event, bracket, "Round 1")[:2]
    taken = [side["entrant_id"] for side in first["sides"]]
    taken[-1] = second["sides"][-1]["entrant_id"]

    refused = client.put(
        f"/cup-series/{first['id']}/sides",
        json={"entrant_ids": taken},
        headers=auth_headers,
    )

    assert refused.status_code == 400, refused.text
    assert refused.json() == {
        "error": f"Entrant {taken[-1]} sits in another lobby of this round; move them"
    }
    assert seated(lobbies(client, event, bracket, "Round 1")[0], seeds) == [1, 8, 9, 16]
    # the same seats in another order stay a lobby's own
    again = client.put(
        f"/cup-series/{first['id']}/sides",
        json={
            "entrant_ids": list(reversed(taken[:-1]))
            + [first["sides"][-1]["entrant_id"]]
        },
        headers=auth_headers,
    )
    assert again.status_code == 200, again.text


def test_a_played_lobby_keeps_its_seats_and_a_two_sided_series_takes_none(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, bracket, _ = ffa()
    generate(client, auth_headers, event, bracket)
    seeds = seeds_of(event)
    lobby = lobbies(client, event, bracket, "Round 1")[0]
    assert play(client, auth_headers, lobby, by_seed(lobby, seeds)).status_code == 200
    settled = client.put(
        f"/cup-series/{lobby['id']}/sides",
        json={"entrant_ids": [side["entrant_id"] for side in lobby["sides"]]},
        headers=auth_headers,
    )
    assert settled.status_code == 400
    assert "settled" in settled.text
    short = client.put(
        f"/cup-series/{lobby['id']}/places",
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
        client.put(f"/cup-series/{lobby['id']}/places", json={"places": []}).status_code
        == 401
    )
    assert (
        client.put(
            f"/cup-series/{lobby['id']}/sides", json={"entrant_ids": []}
        ).status_code
        == 401
    )


def discord_of(user_id: int) -> str:
    from app.models.user import User

    with Session.begin() as session:
        user = session.get(User, user_id)
        assert user is not None and user.discordId
        return user.discordId


def test_a_player_of_the_lobby_reports_its_places_and_an_outsider_cannot(
    client: Client,
    auth_headers: dict[str, str],
    member: Any,  # noqa: ANN401
) -> None:
    event, bracket, _ = ffa()
    generate(client, auth_headers, event, bracket)
    seeds = seeds_of(event)
    first, second = lobbies(client, event, bracket, "Round 1")[:2]
    inside = member(discord_of(first["sides"][0]["user_id"]))
    outside = member(discord_of(second["sides"][0]["user_id"]))

    refused = play(client, outside, first, by_seed(first, seeds))
    assert refused.status_code == 403, refused.text
    reported = play(client, inside, first, by_seed(first, seeds))
    assert reported.status_code == 200, reported.text
    assert sorted(side["place"] for side in reported.json()["sides"]) == [1, 2, 3, 4]


def test_a_withdrawn_player_of_the_lobby_enters_no_places(
    client: Client,
    auth_headers: dict[str, str],
    member: Any,  # noqa: ANN401
) -> None:
    """A player who left the cup no longer enters the places of their lobby;
    a runner still does."""
    event, bracket, _ = ffa()
    generate(client, auth_headers, event, bracket)
    seeds = seeds_of(event)
    [lobby, *_] = lobbies(client, event, bracket, "Round 1")
    left = lobby["sides"][0]["user_id"]
    withdraw(client, auth_headers, event, entrant_of(event, left))

    refused = play(client, member(discord_of(left)), lobby, by_seed(lobby, seeds))
    assert refused.status_code == 403, refused.text
    # the runner places the three seats still in the cup
    placed = play(client, auth_headers, lobby, by_seed(lobby, seeds)[1:])
    assert placed.status_code == 200, placed.text


def test_places_name_every_seat_once_from_one_to_the_seat_count(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, bracket, _ = ffa()
    generate(client, auth_headers, event, bracket)
    lobby = lobbies(client, event, bracket, "Round 1")[0]

    def places(pairs: list[tuple[int, int]]) -> Any:  # noqa: ANN401
        return client.put(
            f"/cup-series/{lobby['id']}/places",
            json={"places": [{"side_no": s, "place": p} for s, p in pairs]},
            headers=auth_headers,
        )

    for pairs, error in (
        ([(1, 1), (2, 2), (3, 3)], "Every side of the lobby needs a place"),
        ([(1, 1), (2, 1), (3, 3), (4, 4)], "The places run from 1 to 4, each once"),
        ([(1, 1), (2, 2), (3, 3), (4, 5)], "The places run from 1 to 4, each once"),
        ([(1, 1), (1, 2), (3, 3), (4, 4)], "Name the place of each seat once"),
    ):
        answer = places(pairs)
        assert answer.status_code == 400, answer.text
        assert answer.json() == {"error": error}
    # a lobby still waiting for its players takes no places
    empty = lobbies(client, event, bracket, "Round 2")[0]
    waiting = play(client, auth_headers, empty, [1, 2, 3, 4])
    assert waiting.status_code == 400, waiting.text
    assert waiting.json() == {"error": "Every seat of the lobby needs its player first"}


def test_a_correction_seats_the_next_round_again_until_it_is_played(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, bracket, _ = ffa()
    generate(client, auth_headers, event, bracket)
    seeds = seeds_of(event)
    for lobby in lobbies(client, event, bracket, "Round 1"):
        assert (
            play(client, auth_headers, lobby, by_seed(lobby, seeds)).status_code == 200
        )
    first = lobbies(client, event, bracket, "Round 1")[0]
    seated_before = {
        seat
        for lobby in lobbies(client, event, bracket, "Round 2")
        for seat in seated(lobby, seeds)
    }
    assert 1 in seated_before and 16 not in seated_before

    # the lobby's last seed in fact won it: he plays on, the top seed goes out
    turned = list(reversed(by_seed(first, seeds)))
    corrected = play(client, auth_headers, first, turned)
    assert corrected.status_code == 200, corrected.text
    seated_after = {
        seat
        for lobby in lobbies(client, event, bracket, "Round 2")
        for seat in seated(lobby, seeds)
    }
    assert 16 in seated_after and 1 not in seated_after

    # once the round below has a result, the round above stays as it is
    below = lobbies(client, event, bracket, "Round 2")[0]
    assert play(client, auth_headers, below, by_seed(below, seeds)).status_code == 200
    late = play(client, auth_headers, first, by_seed(first, seeds))
    assert late.status_code == 409, late.text
    assert late.json() == {"error": "The next round has results; clear them first"}


def test_a_runner_clears_a_lobby_and_the_round_below_gives_its_seats_back(
    client: Client,
    auth_headers: dict[str, str],
    member: Any,  # noqa: ANN401
) -> None:
    event, bracket, _ = ffa()
    generate(client, auth_headers, event, bracket)
    seeds = seeds_of(event)
    for lobby in lobbies(client, event, bracket, "Round 1"):
        assert (
            play(client, auth_headers, lobby, by_seed(lobby, seeds)).status_code == 200
        )
    first = lobbies(client, event, bracket, "Round 1")[0]
    player = member(discord_of(first["sides"][0]["user_id"]))
    url = f"/cup-series/{first['id']}/result"
    assert client.delete(url, headers=player).status_code == 403

    cleared = client.delete(url, headers=auth_headers)

    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["player1_score"] is None
    assert [side["place"] for side in cleared.json()["sides"]] == [None] * 4
    below = lobbies(client, event, bracket, "Round 2")
    assert [seated(lobby, seeds) for lobby in below] == [[0, 0, 0, 0], [0, 0, 0, 0]]


def test_the_final_lobby_decides_the_top_places_of_the_heats(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, bracket, _ = ffa()
    generate(client, auth_headers, event, bracket)
    seeds = seeds_of(event)
    for name in ("Round 1", "Round 2"):
        for lobby in lobbies(client, event, bracket, name):
            assert (
                play(client, auth_headers, lobby, by_seed(lobby, seeds)).status_code
                == 200
            )
    final = lobbies(client, event, bracket, "Final")[0]
    # the weakest finalist wins the final, the strongest comes last
    order = list(reversed(by_seed(final, seeds)))
    assert play(client, auth_headers, final, order).status_code == 200

    rows = table(client, event, bracket)

    sides = {side["side_no"]: side["user_id"] for side in final["sides"]}
    assert [row["user_id"] for row in rows[:4]] == [sides[side] for side in order]
    # the players out in round 2 follow the finalists, ahead of round 1's
    second = {
        side["user_id"]
        for lobby in lobbies(client, event, bracket, "Round 2")
        for side in lobby["sides"]
    } - set(sides.values())
    assert {row["user_id"] for row in rows[4:8]} == second


def test_every_lobby_plays_a_map_of_the_pool_a_runner_can_change(
    client: Client,
    auth_headers: dict[str, str],
    member: Any,  # noqa: ANN401
) -> None:
    from sqlmodel import col, select

    event, bracket, _ = ffa()
    generate(client, auth_headers, event, bracket)
    with Session.begin() as session:
        pool = set(
            session.scalars(
                select(col(DBMapSeason.map_id)).where(
                    col(DBMapSeason.season_id) == event
                )
            )
        )
    first = lobbies(client, event, bracket, "Round 1")
    assert all(row["lobby_map"]["id"] in pool for row in first)
    # a pool of three gives the first three lobbies of a round three maps
    assert len({row["lobby_map"]["id"] for row in first[:3]}) == 3
    assert lobbies(client, event, bracket, "Final")[0]["lobby_map"] is not None

    lobby = first[0]
    other = next(map_id for map_id in pool if map_id != lobby["lobby_map"]["id"])
    player = member(discord_of(lobby["sides"][0]["user_id"]))
    url = f"/cup-series/{lobby['id']}/lobby-map"
    assert client.put(url, json={"map_id": other}, headers=player).status_code == 403
    stranger = maps(1)[0]
    assert (
        client.put(url, json={"map_id": stranger}, headers=auth_headers).status_code
        == 400
    )
    changed = client.put(url, json={"map_id": other}, headers=auth_headers)
    assert changed.status_code == 200, changed.text
    assert changed.json()["lobby_map"]["id"] == other
    play(client, auth_headers, lobby, by_seed(lobby, seeds_of(event)))
    assert (
        client.put(url, json={"map_id": other}, headers=auth_headers).status_code == 400
    )


def test_an_ffa_stage_draws_only_with_a_map_pool(
    client: Client, auth_headers: dict[str, str]
) -> None:
    from sqlalchemy import delete
    from sqlmodel import col

    event, bracket, _ = ffa()
    with Session.begin() as session:
        session.execute(delete(DBMapSeason).where(col(DBMapSeason.season_id) == event))

    refused = client.post(
        f"/events/{event}/stages/{bracket}/generate", headers=auth_headers
    )

    assert refused.status_code == 400, refused.text
    assert refused.json() == {
        "error": "Add at least one map to the pool; every lobby plays one"
    }


def test_a_team_ffa_seats_teams_and_any_player_of_a_seated_team_reports(
    client: Client,
    auth_headers: dict[str, str],
    member: Any,  # noqa: ANN401
) -> None:
    """Four teams of two share one lobby for two games; a seat names its team and
    its players, and any player of a seated team reports the places."""
    from tests.test_stage_engine import team_cup

    event, stage, team_ids, tags = team_cup(
        client,
        auth_headers,
        member,
        StageFormat.ffa,
        lobby_size=4,
        swiss_rounds=2,
        points_by_place="3,2,1,0",
    )
    with Session.begin() as session:
        session.add_all(
            DBMapSeason(season_id=event, map_id=map_id, position=position)
            for position, map_id in enumerate(maps(2))
        )
    generate(client, auth_headers, event, stage)

    games = lobbies(client, event, stage)
    assert len(games) == 2
    seats = games[0]["sides"]
    assert sorted(seat["team"]["id"] for seat in seats) == sorted(team_ids)
    assert all(len(seat["players"]) == 2 for seat in seats)
    assert all(seat["user_id"] is None for seat in seats)

    # the second player of a seated team reports; a player outside the cup cannot
    order = [seat["side_no"] for seat in seats]
    assert play(client, member("99990"), games[0], order).status_code == 403
    reported = play(client, member(tags[2][1]), games[0], order)
    assert reported.status_code == 200, reported.text
    assert sorted(seat["place"] for seat in reported.json()["sides"]) == [1, 2, 3, 4]
    rows = table(client, event, stage)
    assert [row["points"] for row in rows] == [3, 2, 1, 0]
    assert {row["team_id"] for row in rows} == set(team_ids)


def newcomer() -> int:
    """A player who is not in the cup, to swap in for one who is."""
    from app.models.user import User
    from tests.seed import active

    with Session.begin() as session:
        user = User(
            name="Late",
            battle_tags=active("Late#0099"),
            discordTag="late",
            discordId="90099",
            race=Race.HU,
            mmr=1900,
        )
        session.add(user)
        session.flush()
        return ident(user)


def swap(
    client: Client, headers: dict[str, str], event: int, out: int, late: int
) -> Any:  # noqa: ANN401
    """Put the player `late` in the place of the entrant `out`."""
    return client.post(
        f"/events/{event}/entrants/{out}/replace",
        json={"user_id": late, "race": "HU"},
        headers=headers,
    )


def test_a_swap_puts_the_new_player_in_every_open_seat_of_the_old_one(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, bracket, _ = ffa()
    generate(client, auth_headers, event, bracket)
    lobby = lobbies(client, event, bracket, "Round 1")[0]
    seat = lobby["sides"][-1]
    late = newcomer()

    swapped = swap(client, auth_headers, event, seat["entrant_id"], late)

    assert swapped.status_code == 200, swapped.text
    after = lobbies(client, event, bracket, "Round 1")[0]["sides"][-1]
    assert (after["entrant_id"], after["user_id"]) == (swapped.json()["id"], late)
    # the lobby keeps every seat filled, so it takes its places
    placed = play(client, auth_headers, lobby, [1, 2, 3, 4])
    assert placed.status_code == 200, placed.text


def test_a_swap_never_takes_a_seat_of_a_lobby_with_places(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, bracket, _ = ffa()
    generate(client, auth_headers, event, bracket)
    lobby = lobbies(client, event, bracket, "Round 1")[0]
    assert play(client, auth_headers, lobby, [1, 2, 3, 4]).status_code == 200
    seat = lobby["sides"][-1]

    refused = swap(client, auth_headers, event, seat["entrant_id"], newcomer())

    assert refused.status_code == 400, refused.text
    assert "played a match" in refused.text
    kept = lobbies(client, event, bracket, "Round 1")[0]["sides"][-1]
    assert (kept["entrant_id"], kept["user_id"]) == (
        seat["entrant_id"],
        seat["user_id"],
    )


def test_a_player_who_leaves_after_the_draw_keeps_a_left_seat_that_takes_no_place(
    client: Client,
    auth_headers: dict[str, str],
    member: Any,  # noqa: ANN401
) -> None:
    """A withdrawal after the draw marks the seat Left: it takes no place, earns
    no points and sends nobody on, and the next place goes through."""
    event, bracket, _ = ffa()
    generate(client, auth_headers, event, bracket)
    seeds = seeds_of(event)
    first = lobbies(client, event, bracket, "Round 1")[0]
    gone = first["sides"][0]["user_id"]
    left = client.delete(
        f"/events/{event}/entrants/me", headers=member(discord_of(gone))
    )
    assert left.status_code == 204, left.text

    first = lobbies(client, event, bracket, "Round 1")[0]
    assert seated(first, seeds) == [1, 8, 9, 16]
    assert [side["left"] for side in first["sides"]] == [True, False, False, False]
    every = play(client, auth_headers, first, by_seed(first, seeds))
    assert every.status_code == 400, every.text
    assert every.json() == {"error": "Seat 1 left the cup and takes no place"}
    # the three other seats take places 1 to 3
    gap = client.put(
        f"/cup-series/{first['id']}/places",
        json={
            "places": [{"side_no": s, "place": p} for s, p in ((2, 1), (3, 2), (4, 4))]
        },
        headers=auth_headers,
    )
    assert gap.status_code == 400, gap.text
    assert gap.json() == {"error": "The places run from 1 to 3, each once"}
    placed = play(client, auth_headers, first, by_seed(first, seeds)[1:])
    assert placed.status_code == 200, placed.text
    assert [side["place"] for side in placed.json()["sides"]] == [None, 1, 2, 3]

    settle(client, auth_headers, event, bracket)
    through = {
        seat
        for lobby in lobbies(client, event, bracket, "Round 2")
        for seat in seated(lobby, seeds)
    }
    assert {8, 9} <= through and 1 not in through
    points = {
        seeds[row["user_id"]]: row["points"] for row in table(client, event, bracket)
    }
    assert 1 not in points
    # the lobby pays 4, 3, 2 to the three places it gave, as drawn
    assert (points[8], points[9], points[16]) == (4, 3, 2)


def test_a_placed_player_who_leaves_keeps_the_place_and_the_next_one_goes_through(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """A runner withdraws the winner of a played lobby before the round below is
    seated: the seat keeps its place, and the runner-up and the third go on."""
    event, bracket, _ = ffa()
    withdraw(client, auth_headers, event, entrant_of(event, players_of(event)[-1]))
    generate(client, auth_headers, event, bracket)
    seeds = seeds_of(event)
    # a withdrawal before the draw leaves no seat
    drawn = lobbies(client, event, bracket, "Round 1")
    assert 16 not in {seat for lobby in drawn for seat in seated(lobby, seeds)}
    first = drawn[0]
    assert play(client, auth_headers, first, by_seed(first, seeds)).status_code == 200
    withdraw(
        client, auth_headers, event, entrant_of(event, first["sides"][0]["user_id"])
    )

    first = lobbies(client, event, bracket, "Round 1")[0]
    assert [(side["place"], side["left"]) for side in first["sides"]] == [
        (1, False),
        (2, False),
        (3, False),
    ]
    settle(client, auth_headers, event, bracket)

    # the runner-up and the third of the first lobby rank with the winners and
    # the runners-up of the other lobbies, and the snake deals them
    assert [
        seated(row, seeds) for row in lobbies(client, event, bracket, "Round 2")
    ] == [
        [8, 4, 9, 5],
        [2, 3, 7, 6],
    ]

    # a correction of the played lobby places the player who left, whose place stands
    again = play(client, auth_headers, first, by_seed(first, seeds))
    assert again.status_code == 200, again.text
    first = lobbies(client, event, bracket, "Round 1")[0]
    assert [side["place"] for side in first["sides"]] == [1, 2, 3]
