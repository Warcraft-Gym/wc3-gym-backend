"""Generate the series of a stage, follow its results and rank its entrants.

The engine reads the shared rows only and never branches on the kind of an
event. A GNL stage is drafted by its admin and its captains, so it refuses to
generate one, and a series with no feeders answers nothing when it is scored
or reopened: every GNL payload holds.
"""

from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core import brackets
from app.core.db import Session
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.scoring import wins_needed
from app.models.base import ident
from app.models.enums import StageFormat
from app.models.event_division import EventDivision
from app.models.event_entrant import EventEntrant
from app.models.event_stage import DivisionStandings, EventStage, StandingRow
from app.models.relationships import DBEventRound, EventRoundPublic
from app.models.series import (
    ResultKindWrite,
    Series,
    SeriesPublic,
    StageSeriesPublic,
    StageSeriesRow,
)
from app.models.user import User
from app.services import derived

# The formats whose last round is the final, so every division ends together
BRACKETS = (StageFormat.single_elimination, StageFormat.double_elimination)


def scored(row: Series) -> bool:
    """Whether the series carries a result."""
    return row.player1_score is not None or row.player2_score is not None


def winner_of(row: Series) -> int | None:
    """The user the series sends on: nobody while it is unscored or drawn."""
    return _side(row, takes_loser=False)


def wins_of(session: OrmSession, row: Series) -> int:
    """The maps a win takes: a fixture follows its season's map rules, and a
    bracket series the best of its round, else the best of its stage."""
    if row.match is not None:
        return wins_needed(row.match.season.map_rules if row.match.season else None)
    round_row = session.get(DBEventRound, row.round_id) if row.round_id else None
    stage = _stage_of(session, row)
    best_of = (round_row.best_of if round_row else None) or (
        stage.best_of if stage else None
    )
    return best_of // 2 + 1 if best_of else wins_needed(None)


def generate(event_id: int, stage_id: int) -> dict[str, int]:
    """Create every series of the stage from the locked seeds, per division.

    Each bracket column is one round under the stage, and the divisions share
    those rounds: a bracket aligns on its final, a table on its first round.
    """
    with Session.begin() as session:
        stage = _stage(session, event_id, stage_id)
        if stage.format is StageFormat.gnl:
            raise BadRequestError(
                "A GNL stage is drafted by its admin and its captains, not generated"
            )
        if _series_of(session, stage_id):
            raise BadRequestError("This stage already holds series")
        fields = _fields(_entrants(session, event_id))
        for field in fields.values():
            if len(field) < 2:
                raise BadRequestError("A division needs two entrants to generate")
        plans = {
            division: _plan(stage, len(field)) for division, field in fields.items()
        }
        depth = max(len(plan.rounds) for plan in plans.values())
        first = _next_number(session, event_id)
        rounds: dict[int, DBEventRound] = {}
        made: list[Series] = []
        for division_id, field in fields.items():
            plan = plans[division_id]
            shift = depth - len(plan.rounds) if stage.format in BRACKETS else 0
            rows: list[Series] = []
            counts: dict[int, int] = {}
            for planned in plan.series:
                place = planned.round + shift
                round_row = rounds.get(place)
                if round_row is None:
                    round_row = DBEventRound(
                        stage_id=stage_id,
                        season_id=event_id,
                        number=first + place,
                        name=plan.rounds[planned.round],
                    )
                    session.add(round_row)
                    session.flush()
                    rounds[place] = round_row
                counts[place] = counts.get(place, 0) + 1
                rows.append(
                    _row(session, stage, round_row, division_id, field, rows, planned)
                )
                rows[-1].sequence = counts[place]
            made += rows
        session.flush()
        # A padded pair was written as a walkover; its winner moves on now
        for row in made:
            if scored(row):
                on_scored(session, row)
        return {"series": len(made), "rounds": len(rounds)}


def on_scored(session: OrmSession, row: Series) -> None:
    """Fill every slot that feeds from this series, and follow the chain down."""
    for other in _downstream(session, ident(row)):
        filled = False
        if other.slot1_from_series_id == row.id and other.player1_id is None:
            other.player1_id = _side(row, other.slot1_takes_loser)
            filled = other.player1_id is not None
        if other.slot2_from_series_id == row.id and other.player2_id is None:
            other.player2_id = _side(row, other.slot2_takes_loser)
            filled = filled or other.player2_id is not None
        if filled and other.host_player_id == 0:
            other.host_player_id = other.player1_id or 0
        session.flush()
        _settle(session, other)


def on_reopened(session: OrmSession, row: Series, force: bool = False) -> None:
    """Take the side back off every series this one fed, and clear their results.

    A cleared series may already carry a result, which is a result an admin is
    about to lose, so the reopen refuses it unless the caller forces it.
    """
    below = _closure(session, row)
    if not force and any(scored(other) for other in below):
        raise BadRequestError(
            "A later series already carries a result; reopen it with force"
        )
    cleared = {ident(row)} | {ident(other) for other in below}
    for other in below:
        if other.slot1_from_series_id in cleared:
            other.player1_id = None
        if other.slot2_from_series_id in cleared:
            other.player2_id = None
        other.player1_score = None
        other.player2_score = None
        other.result_kind = "played"
    session.flush()


def after_score(
    session: OrmSession,
    row: Series,
    was_scored: bool,
    was_winner: int | None,
    force: bool = False,
) -> None:
    """Follow a score change into the bracket. A series with no feeders and
    nothing below it, which is every GNL series, changes nothing here.

    A correction that turns the series around is a reopen and a fresh score in
    one write: the sides below it move to the new winner and the new loser, and
    a later result is lost, so it takes the same force as a reopen.
    """
    now = scored(row)
    if now and was_scored:
        if was_winner == winner_of(row):
            return
        on_reopened(session, row, force)
        on_scored(session, row)
        _auto_advance(session, row)
        return
    if now == was_scored:
        return
    if now:
        on_scored(session, row)
        _auto_advance(session, row)
    else:
        on_reopened(session, row, force)


def set_result_kind(series_id: int, data: ResultKindWrite) -> SeriesPublic:
    """Score a series that was not played, and carry its winner downstream."""
    with Session.begin() as session:
        row = session.get(Series, series_id)
        if row is None:
            raise NotFoundError("Series not found")
        if scored(row):
            raise BadRequestError("This series already carries a result")
        _award(session, row, data.winner == 1, data.result_kind)
        on_scored(session, row)
        _auto_advance(session, row)
        public = SeriesPublic.from_series(row)
        derived.fill_series(session, [public])
        return public


def standings_of(event_id: int, stage_id: int) -> list[DivisionStandings]:
    """The table of every division of the stage, from its points and its format."""
    with Session.begin() as session:
        return _tables(session, event_id, _stage(session, event_id, stage_id))


def series_of(event_id: int, stage_id: int) -> StageSeriesPublic:
    """The rounds of the stage and every series it holds, in drawing order."""
    with Session.begin() as session:
        stage = _stage(session, event_id, stage_id)
        rounds = session.scalars(
            select(DBEventRound)
            .where(col(DBEventRound.stage_id) == ident(stage))
            .order_by(col(DBEventRound.number))
        ).all()
        # The series read joins no round: Season.round_count is a correlated
        # subquery over that table, and a join leaves the subquery no FROM
        numbers = {ident(row): row.number for row in rounds}
        held = session.scalars(
            select(Series)
            .options(*Series._list_eager_options())
            .where(col(Series.round_id).in_(numbers))
        ).all()
        rows = [
            StageSeriesRow.from_series_reduced(row)
            for row in sorted(held, key=lambda row: _drawn(numbers, row))
        ]
        derived.fill_series(session, rows)
        return StageSeriesPublic(
            rounds=[EventRoundPublic.from_row(row) for row in rounds], series=rows
        )


def advance(event_id: int, stage_id: int) -> dict[str, int]:
    """Seed the next stage from the top places of every division's table."""
    with Session.begin() as session:
        stage = _stage(session, event_id, stage_id)
        following = _next_stage(session, event_id, stage)
        if following is None:
            raise BadRequestError("This stage is the last one of the event")
        return {"seeded": _advance(session, event_id, stage)}


def _drawn(numbers: dict[int, int], row: Series) -> tuple[int, int, int, int]:
    """Where a series is drawn: its round, its division, its place, its id."""
    return (
        numbers.get(row.round_id or 0, 0),
        row.division_id or 0,
        row.sequence or 0,
        ident(row),
    )


def _row(
    session: OrmSession,
    stage: EventStage,
    round_row: DBEventRound,
    division_id: int | None,
    field: Sequence[EventEntrant],
    rows: Sequence[Series],
    planned: brackets.PlannedSeries,
) -> Series:
    """Write one planned series; a padded pair is a walkover for the side it has."""
    user1, feeder1 = _slot(field, rows, planned.slot1)
    user2, feeder2 = _slot(field, rows, planned.slot2)
    row = Series(
        round_id=ident(round_row),
        division_id=division_id,
        host_player_id=user1 or 0,
        player1_id=user1,
        player2_id=user2,
        slot1_from_series_id=feeder1,
        slot1_takes_loser=planned.slot1.takes_loser,
        slot2_from_series_id=feeder2,
        slot2_takes_loser=planned.slot2.takes_loser,
    )
    session.add(row)
    session.flush()
    if feeder1 is None and feeder2 is None and (user1 is None) != (user2 is None):
        wins = (round_row.best_of or stage.best_of) // 2 + 1
        _award(session, row, user1 is not None, "walkover", wins)
    return row


def _slot(
    field: Sequence[EventEntrant], rows: Sequence[Series], slot: brackets.Slot
) -> tuple[int | None, int | None]:
    """The user this slot opens with, and the series it takes its side from."""
    if slot.seed is not None:
        return field[slot.seed - 1].user_id, None
    if slot.feeder is not None:
        return None, ident(rows[slot.feeder])
    return None, None


def _award(
    session: OrmSession,
    row: Series,
    to_first: bool,
    kind: str,
    wins: int | None = None,
) -> None:
    """Write a result no game was played for, to one side of the series."""
    maps = wins if wins is not None else wins_of(session, row)
    row.player1_score, row.player2_score = (maps, 0) if to_first else (0, maps)
    row.result_kind = kind
    session.flush()


def _side(row: Series, takes_loser: bool) -> int | None:
    """The winner of the series, or its loser; a draw sends neither on."""
    if row.player1_score is None or row.player2_score is None:
        return None
    if row.player1_score == row.player2_score:
        return None
    first = row.player1_score > row.player2_score
    return row.player2_id if first == takes_loser else row.player1_id


def _settle(session: OrmSession, row: Series) -> None:
    """A series nobody plays is a walkover: a bye, or a reset the final settled."""
    if scored(row):
        return
    final = _reset_final(session, row)
    if final is not None:
        # A bracket reset is played only when the lower bracket side takes the final
        if scored(final) and _side(final, takes_loser=False) == final.player1_id:
            _award(session, row, to_first=True, kind="walkover")
            on_scored(session, row)
        return
    first, first_known = _resolved(session, row, 1)
    second, second_known = _resolved(session, row, 2)
    if not (first_known and second_known) or (first is None) == (second is None):
        return
    _award(session, row, first is not None, "walkover")
    on_scored(session, row)


def _reset_final(session: OrmSession, row: Series) -> Series | None:
    """The grand final a bracket reset hangs off, which is the one series it
    takes both its sides from: the winner in front, the loser behind."""
    if (
        row.slot1_from_series_id is None
        or row.slot1_from_series_id != row.slot2_from_series_id
        or row.slot1_takes_loser
        or not row.slot2_takes_loser
    ):
        return None
    return session.get(Series, row.slot1_from_series_id)


def _resolved(session: OrmSession, row: Series, slot: int) -> tuple[int | None, bool]:
    """The user in one slot, and whether its feeder has answered at all.

    A scored feeder that sends nobody on, which is the loser of a walkover,
    leaves the slot known and empty.
    """
    side = row.player1_id if slot == 1 else row.player2_id
    if side is not None:
        return side, True
    feeder_id = row.slot1_from_series_id if slot == 1 else row.slot2_from_series_id
    feeder = session.get(Series, feeder_id) if feeder_id else None
    return None, feeder is not None and scored(feeder)


def _downstream(session: OrmSession, series_id: int) -> Sequence[Series]:
    """Every series that takes one of its sides from this one."""
    return session.scalars(
        select(Series)
        .where(
            or_(
                col(Series.slot1_from_series_id) == series_id,
                col(Series.slot2_from_series_id) == series_id,
            )
        )
        .order_by(col(Series.id))
    ).all()


def _closure(session: OrmSession, row: Series) -> list[Series]:
    """Every series below this one, however far down; each one listed once."""
    found: list[Series] = []
    seen = {ident(row)}
    queue = list(_downstream(session, ident(row)))
    while queue:
        other = queue.pop(0)
        if ident(other) in seen:
            continue
        seen.add(ident(other))
        found.append(other)
        queue += _downstream(session, ident(other))
    return found


def _stage(session: OrmSession, event_id: int, stage_id: int) -> EventStage:
    stage = session.get(EventStage, stage_id)
    if stage is None or stage.event_id != event_id:
        raise NotFoundError(f"Stage not found by id: {stage_id}")
    return stage


def _stage_of(session: OrmSession, row: Series) -> EventStage | None:
    """The stage a series is played in, through the round it belongs to."""
    round_row = session.get(DBEventRound, row.round_id) if row.round_id else None
    if round_row is None or round_row.stage_id is None:
        return None
    return session.get(EventStage, round_row.stage_id)


def _next_stage(
    session: OrmSession, event_id: int, stage: EventStage
) -> EventStage | None:
    return session.scalars(
        select(EventStage)
        .where(
            col(EventStage.event_id) == event_id,
            col(EventStage.position) > stage.position,
        )
        .order_by(col(EventStage.position))
    ).first()


def _series_of(session: OrmSession, stage_id: int | None) -> Sequence[Series]:
    """Every series the stage holds, in play order, through its rounds."""
    return session.scalars(
        select(Series)
        .join(DBEventRound, col(DBEventRound.id) == col(Series.round_id))
        .where(col(DBEventRound.stage_id) == stage_id)
        .order_by(col(DBEventRound.number), col(Series.sequence), col(Series.id))
    ).all()


def _next_number(session: OrmSession, event_id: int) -> int:
    """The round number the stage starts at; the rounds of one event are one run."""
    highest = session.scalar(
        select(func.max(col(DBEventRound.number))).where(
            col(DBEventRound.season_id) == event_id
        )
    )
    return (highest or 0) + 1


def _entrants(
    session: OrmSession, event_id: int
) -> dict[int | None, list[EventEntrant]]:
    """Every entrant of every division in seed order; one field without divisions."""
    divisions = session.scalars(
        select(EventDivision)
        .where(col(EventDivision.event_id) == event_id)
        .order_by(col(EventDivision.position))
    ).all()
    entrants = session.scalars(
        select(EventEntrant)
        .where(
            col(EventEntrant.event_id) == event_id,
            col(EventEntrant.withdrawn_at).is_(None),
        )
        .order_by(
            col(EventEntrant.seed).is_(None),
            col(EventEntrant.seed),
            col(EventEntrant.id),
        )
    ).all()
    if not divisions:
        return {None: list(entrants)}
    return {
        ident(division): [
            entrant for entrant in entrants if entrant.division_id == division.id
        ]
        for division in divisions
    }


def _fields(
    everyone: dict[int | None, list[EventEntrant]],
) -> dict[int | None, list[EventEntrant]]:
    """What a generate plays over: the seeded entrants of every division.

    A seed is what a locked stage plays over, so once any entrant carries one
    the field is the seeded entrants alone: `advance` seeds the ones that go
    through and clears the rest.
    """
    seeded = {
        division_id: [entrant for entrant in field if entrant.seed is not None]
        for division_id, field in everyone.items()
    }
    return seeded if any(seeded.values()) else everyone


def _plan(stage: EventStage, size: int) -> brackets.Plan:
    """The shape the stage plays over a field of this size."""
    match stage.format:
        case StageFormat.single_elimination:
            return brackets.elimination_plan(size, third_place=stage.third_place)
        case StageFormat.double_elimination:
            return brackets.double_elimination_plan(
                size, grand_final=stage.grand_final_modifier
            )
        case StageFormat.round_robin:
            return brackets.round_robin_plan(size, stage.series_per_entrant_per_round)
        case StageFormat.koth:
            return brackets.koth_chain(size)
        case _:
            raise BadRequestError(f"format_not_built: {stage.format.value}")


def _tables(
    session: OrmSession, event_id: int, stage: EventStage
) -> list[DivisionStandings]:
    """One table per division, from the series the stage holds.

    The field of a table is the entrants its own series play over, so the table
    of a finished stage keeps everyone that played it after `advance` has
    reseeded the event for the next stage.
    """
    played: dict[int | None, list[Series]] = {}
    for row in _series_of(session, stage.id):
        played.setdefault(row.division_id, []).append(row)
    names = {
        ident(division): division.name
        for division in session.scalars(
            select(EventDivision).where(col(EventDivision.event_id) == event_id)
        )
    }
    everyone = _entrants(session, event_id)
    seeds = _fields(everyone)
    return [
        DivisionStandings(
            division_id=division_id,
            division_name=names.get(division_id) if division_id else None,
            rows=_table(
                session,
                stage,
                _sides_of(field, played.get(division_id, []))
                or seeds.get(division_id, []),
                played.get(division_id, []),
            ),
        )
        for division_id, field in everyone.items()
    ]


def _sides_of(
    field: Sequence[EventEntrant], series: Sequence[Series]
) -> list[EventEntrant]:
    """The entrants of the division that stand in one of its series, in seed order."""
    sides = {row.player1_id for row in series} | {row.player2_id for row in series}
    sides.discard(None)
    return [entrant for entrant in field if entrant.user_id in sides]


def _table(
    session: OrmSession,
    stage: EventStage,
    field: Sequence[EventEntrant],
    series: Sequence[Series],
) -> list[StandingRow]:
    """One division's places, from the stage's points and the format it plays."""
    entrants = {
        entrant.user_id: entrant for entrant in field if entrant.user_id is not None
    }
    order = list(entrants)
    results = [
        (
            row.player1_id,
            row.player2_id,
            row.player1_score or 0,
            row.player2_score or 0,
        )
        for row in series
        if scored(row) and row.player1_id in entrants and row.player2_id in entrants
    ]
    # The tie breaks run points, game difference then head to head, which is
    # what every stage's ranking_rule holds today
    table = brackets.standings(
        order,
        results,
        brackets.Points(
            stage.points_series_won, stage.points_series_drawn, stage.points_game_won
        ),
    )
    if stage.format in BRACKETS:
        reached = _reached(session, order, series)
        table = sorted(table, key=lambda line: reached[line.entrant], reverse=True)
    elif stage.format is StageFormat.koth:
        king = _king(series)
        table = sorted(table, key=lambda line: line.entrant == king, reverse=True)
    counted = _counted(order, results)
    names = _names(session, order)
    return [
        StandingRow(
            position=place,
            entrant_id=ident(entrants[line.entrant]),
            user_id=line.entrant,
            team_id=entrants[line.entrant].team_id,
            name=names.get(line.entrant),
            points=line.points,
            game_diff=line.game_diff,
            **counted[line.entrant],
        )
        for place, line in enumerate(table, start=1)
    ]


def _reached(
    session: OrmSession, order: Sequence[int], series: Sequence[Series]
) -> dict[int, tuple[int, int]]:
    """How far each entrant went: the last round he stood in, then his wins."""
    numbers = {
        round_row.id: round_row.number
        for round_row in session.scalars(
            select(DBEventRound).where(
                col(DBEventRound.id).in_({row.round_id for row in series})
            )
        )
    }
    depth = dict.fromkeys(order, 0)
    won = dict.fromkeys(order, 0)
    for row in series:
        for side in (row.player1_id, row.player2_id):
            if side in depth:
                depth[side] = max(depth[side], numbers.get(row.round_id, 0))
        winner = _side(row, takes_loser=False)
        if winner in won:
            won[winner] += 1
    return {entrant: (depth[entrant], won[entrant]) for entrant in order}


def _king(series: Sequence[Series]) -> int | None:
    """The winner of the last series the chain has scored, who holds the throne."""
    done = [row for row in series if scored(row)]
    return _side(done[-1], takes_loser=False) if done else None


def _counted(
    order: Sequence[int], results: Sequence[tuple[int, int, int, int]]
) -> dict[int, dict[str, int]]:
    """Series played, won and lost, and the games either way, per entrant."""
    tally = {
        entrant: {"played": 0, "won": 0, "lost": 0, "games_won": 0, "games_lost": 0}
        for entrant in order
    }
    for first, second, first_games, second_games in results:
        for own, other, games, other_games in (
            (first, second, first_games, second_games),
            (second, first, second_games, first_games),
        ):
            tally[own]["played"] += 1
            tally[own]["games_won"] += games
            tally[own]["games_lost"] += other_games
            if games > other_games:
                tally[own]["won"] += 1
            elif games < other_games:
                tally[own]["lost"] += 1
    return tally


def _names(session: OrmSession, order: Sequence[int]) -> dict[int, str]:
    """The name of every player in the table, in one read."""
    if not order:
        return {}
    return {
        ident(user): user.name
        for user in session.scalars(select(User).where(col(User.id).in_(list(order))))
    }


def _auto_advance(session: OrmSession, row: Series) -> None:
    """A stage that carries its places forward does it on the last result."""
    stage = _stage_of(session, row)
    if stage is None or not stage.auto_advance:
        return
    if _next_stage(session, stage.event_id, stage) is None:
        return
    if any(not scored(other) for other in _series_of(session, stage.id)):
        return
    _advance(session, stage.event_id, stage)


def _advance(session: OrmSession, event_id: int, stage: EventStage) -> int:
    """Seed the top places of every division; the rest lose their seed."""
    rows = _series_of(session, stage.id)
    if not rows or any(not scored(row) for row in rows):
        raise BadRequestError("Every series of the stage needs a result first")
    carried: set[int] = set()
    for table in _tables(session, event_id, stage):
        top = table.rows[: stage.advance_count] if stage.advance_count else table.rows
        for place, line in enumerate(top, start=1):
            entrant = session.get(EventEntrant, line.entrant_id)
            if entrant is None:
                continue
            entrant.seed = place
            entrant.seed_source = "previous_stage"
            carried.add(line.entrant_id)
    for entrant in session.scalars(
        select(EventEntrant).where(col(EventEntrant.event_id) == event_id)
    ):
        if ident(entrant) not in carried:
            entrant.seed = None
    session.flush()
    return len(carried)
