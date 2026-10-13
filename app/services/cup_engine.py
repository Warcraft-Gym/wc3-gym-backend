"""Draw a cup's stages, follow their results and rank their entrants.

The engine reads and writes the cup's own tables (`cup_series` and its sides)
and nothing of GNL or KOTH, which keep `series` and app.services.stage_engine.
A stage plans its shape from its format, and a result fills the series below
it through the feeders, settles byes and forfeits, and on a stage played
straight away draws the next Swiss round or the stage after it.

A team side names no player: the team entrant stands on it, and every member
of the team acts for it.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core import brackets
from app.core.best_of import parse_plan
from app.core.db import Session
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.core.outcome import entrant_of, scored, side_user, stands_on_side, won_slot
from app.core.scoring import wins_of
from app.models.base import ident
from app.models.cup_series import (
    CupSeries,
    CupSeriesPublic,
    CupSeriesSide,
    CupStagePublic,
)
from app.models.cup_team import CupTeam, CupTeamMember, team_summary
from app.models.enums import EventKind, SchedulingMode, StageFormat
from app.models.event_division import EventDivision
from app.models.event_entrant import EventEntrant
from app.models.event_stage import (
    RANKING_RULE,
    SWISS_RANKING_RULE,
    DivisionStandings,
    EventStage,
    StandingRow,
)
from app.models.relationships import DBEventRound, EventRoundPublic
from app.models.season import Season
from app.models.series import ResultKindWrite
from app.models.series_side import LobbySidesWrite, PlacesWrite, SeriesSidePublic
from app.models.types import utcnow
from app.models.user import User, UserSummaryPublic
from app.services import cup_reads, organizers

# The formats whose last round is the final, so every division ends together
BRACKETS = (
    StageFormat.single_elimination,
    StageFormat.double_elimination,
    StageFormat.placement,
)
# The formats that draw one round at a time, from the table as it stands
BY_ROUND = (StageFormat.swiss,)
# Seeds the unseeded entrants inside the draw's transaction, so a refusal writes none
type SeedFill = Callable[[OrmSession, EventStage], None]


def series_wins(session: OrmSession, row: CupSeries) -> int:
    """The maps a win takes, from the best-of the series plays under."""
    return wins_of(cup_reads.rules_of(session, row).best_of)


def generate(
    event_id: int,
    stage_id: int,
    division_id: int | None = None,
    fill: SeedFill | None = None,
) -> dict[str, int]:
    """Create every series of the stage from the seeds, per division, and lock them.

    Each bracket column is one round under the stage, and the divisions share
    those rounds: a bracket aligns on its final, a table on its first round. A
    named division draws alone into the rounds the stage already holds, so a
    stage whose divisions fill one at a time opens each as it is ready. `fill`
    seeds the unseeded entrants first, in the same transaction as the draw.
    """
    with Session.begin() as session:
        return _generate(session, event_id, stage_id, division_id, fill)


def _generate(
    session: OrmSession,
    event_id: int,
    stage_id: int,
    division_id: int | None = None,
    fill: SeedFill | None = None,
) -> dict[str, int]:
    """The draw of `generate`, inside the caller's transaction, so a result
    that ends a stage can draw the one after it."""
    stage = _stage(session, event_id, stage_id)
    if stage.format is StageFormat.gnl:
        raise BadRequestError(
            "A GNL stage is drafted by its admin and its captains, not generated"
        )
    if stage.format is StageFormat.koth:
        raise BadRequestError(
            "A KOTH stage is paired by its admin during the event, not generated"
        )
    event = _cup(session, event_id)
    drawn = _series_of(session, stage_id)
    if division_id is None and drawn:
        raise BadRequestError("This stage already holds series")
    if any(row.division_id == division_id for row in drawn):
        raise BadRequestError("This division already holds series")
    if division_id is not None and stage.format in BRACKETS:
        raise BadRequestError("A bracket stage draws every division together")
    if fill is not None:
        fill(session, stage)
    _hold_placed(session, event_id)
    fields = _fields(_entrants(session, event_id))
    _hold_minimum(session, stage, fields)
    cup_reads.hold_pool(session, event)
    # a team cup draws complete teams only
    from app.services.cup_teams import incomplete

    short = incomplete(session, event)
    if short:
        raise BadRequestError(
            "Every team needs all its players before the draw: " + ", ".join(short)
        )
    if division_id is not None:
        fields = {division_id: fields.get(division_id, [])}
    for field in fields.values():
        if len(field) < 2:
            raise BadRequestError("A division needs two entrants to generate")
    sizes = _side_sizes(
        session, [entrant for field in fields.values() for entrant in field]
    )
    # The largest roster stands in while a bracket pair is not drawn yet
    size = max(sizes.values(), default=1)
    draws = _draws(session, stage, list(fields.items()))
    if any(len(field) < 2 for _, field in draws):
        raise BadRequestError("A group needs two entrants; the group size is small")
    plans = [_plan(stage, len(field)) for _, field in draws]
    depth = max(len(plan.rounds) for plan in plans)
    # A bracket part the stage names plays its own best-of; null follows the stage
    best_of_by_part = parse_plan(stage.best_of_by_round)
    held = {row.number: row for row in _rounds_of(session, stage_id)}
    first = min(held) if held else _next_number(session, event_id)
    rounds: dict[int, DBEventRound] = {
        number - first: row for number, row in held.items()
    }
    made: list[CupSeries] = []
    # The groups of a division write into one run of sequences per round
    counts: dict[tuple[int | None, int], int] = {}
    for (division, field), plan in zip(draws, plans, strict=True):
        shift = depth - len(plan.rounds) if stage.format in BRACKETS else 0
        rows: list[CupSeries] = []
        for planned in plan.series:
            place = planned.round + shift
            round_row = rounds.get(place)
            if round_row is None:
                role = plan.role(planned.round)
                round_row = DBEventRound(
                    stage_id=stage_id,
                    season_id=event_id,
                    number=first + place,
                    name=plan.rounds[planned.round],
                    best_of=best_of_by_part.get(role) if role else None,
                )
                session.add(round_row)
                session.flush()
                rounds[place] = round_row
            counts[division, place] = counts.get((division, place), 0) + 1
            rows.append(
                _row(
                    session,
                    stage,
                    round_row,
                    division,
                    field,
                    rows,
                    planned,
                    size,
                    sizes,
                )
            )
            rows[-1].sequence = counts[division, place]
        made += rows
    session.flush()
    # Padded walkovers fill every slot below before any series below settles
    walkovers = [row for row in made if scored(row)]
    for row in walkovers:
        _fill_below(session, row)
    for row in walkovers:
        on_scored(session, row)
    stage.seeds_locked_at = stage.seeds_locked_at or utcnow()
    return {"series": len(made), "rounds": len(rounds) - len(held)}


def undraw(event_id: int, stage_id: int, confirm: bool = False) -> dict[str, int]:
    """Take a stage's draw back: its rounds go, and every series with them.

    The rounds' keys take the series, and the series' keys take their games,
    vetoes and sides, so the stage stands as it did before the
    draw, with its entrants, and its seeds open again. A finished event keeps
    its draw, and a later stage that is drawn already is taken back first. A
    stage whose series hold results keeps them unless the caller confirms.
    """
    with Session.begin() as session:
        stage = _stage(session, event_id, stage_id)
        if stage.format in (StageFormat.gnl, StageFormat.koth):
            raise BadRequestError(
                "A GNL or KOTH stage is not drawn, so it has no draw to undo"
            )
        event = session.get(Season, event_id)
        if event is not None and event.closed_at is not None:
            raise BadRequestError(
                "The event is finished; reopen it before the draw is undone"
            )
        rows = list(_series_of(session, stage_id))
        if not rows:
            raise BadRequestError("This stage holds no draw to undo")
        following = _next_stage(session, event_id, stage)
        if following is not None and _series_of(session, ident(following)):
            raise BadRequestError("A later stage is drawn; undo its draw first")
        results = sum(
            1 for row in rows if scored(row) and row.entrant1_id and row.entrant2_id
        )
        if results and not confirm:
            raise ApiError(
                409,
                {
                    "error": f"{results} series of this stage hold results; "
                    "confirm to delete them"
                },
            )
        for round_row in _rounds_of(session, stage_id):
            session.delete(round_row)
        stage.seeds_locked_at = None
        session.flush()
        return {"series": len(rows), "results": results}


def generate_next_round(
    event_id: int,
    stage_id: int,
    division_id: int | None = None,
    fill: SeedFill | None = None,
) -> CupStagePublic:
    """Draw one more round of a stage that pairs a round at a time, per division.

    The pairing reads the table as it stands, so every series already drawn
    needs a result first. Each entrant takes the best-placed opponent he has
    not met, which keeps a pair inside its score group while one is free
    there, and an odd field gives the bye to the lowest entrant without one,
    as a walkover series holding a single side. The first call on an empty
    stage pairs round 1 from the seeds and locks them; `fill` seeds the
    unseeded entrants first, in the same transaction as the draw.
    """
    with Session.begin() as session:
        _cup(session, event_id)
        made, drew = _draw_round(session, event_id, stage_id, division_id, fill)
        read = _stage_rows(session, made)
        rows = _publics(session, read)
        _fill_seeds(rows, read)
        return CupStagePublic(
            rounds=[EventRoundPublic.from_row(row) for row in drew.values()],
            series=rows,
        )


def _draw_round(
    session: OrmSession,
    event_id: int,
    stage_id: int,
    division_id: int | None = None,
    fill: SeedFill | None = None,
) -> tuple[list[CupSeries], dict[int, DBEventRound]]:
    """The draw of `generate_next_round`, inside the caller's transaction, so
    the last result of a round can draw the next one. Answers the series it
    wrote and the round rows it drew them into."""
    stage = _stage(session, event_id, stage_id)
    if not _draws_by_round(stage):
        raise BadRequestError("This stage draws every round at once, not one by one")
    drawn = _series_of(session, stage_id)
    held = list(_rounds_of(session, stage_id))
    if fill is not None:
        fill(session, stage)
    if not drawn:
        _hold_placed(session, event_id)
    fields = _fields(_entrants(session, event_id))
    if not drawn:
        _hold_minimum(session, stage, fields)
        stage.seeds_locked_at = stage.seeds_locked_at or utcnow()
    if division_id is not None:
        fields = {division_id: fields.get(division_id, [])}
    sizes = _side_sizes(
        session, [entrant for field in fields.values() for entrant in field]
    )
    # The largest roster stands in while a bracket pair is not drawn yet
    size = max(sizes.values(), default=1)
    made: list[CupSeries] = []
    drew: dict[int, DBEventRound] = {}
    for division, field in fields.items():
        played = [row for row in drawn if row.division_id == division]
        if len(field) < 2:
            raise BadRequestError("A division needs two entrants to draw a round")
        if any(not scored(row) for row in played):
            raise BadRequestError(
                "Every series of the round before needs a result first"
            )
        place = len({row.round_id for row in played})
        limit = _round_limit(stage, len(field))
        if limit is not None and place >= limit:
            raise BadRequestError(f"This stage plays {limit} rounds and has drawn them")
        order = [line.entrant_id for line in _table(session, stage, field, played)]
        pairs = brackets.swiss_pairs(
            order, [(row.entrant1_id, row.entrant2_id) for row in played]
        )
        if pairs is None:
            raise BadRequestError("This division has played every pairing it has")
        round_row = held[place] if place < len(held) else None
        if round_row is None:
            round_row = DBEventRound(
                stage_id=stage_id,
                season_id=event_id,
                number=_next_number(session, event_id),
                name=f"Round {place + 1}",
            )
            session.add(round_row)
            session.flush()
            held.append(round_row)
        drew[place] = round_row
        entrants = {ident(entrant): entrant for entrant in field}
        for sequence, (top, bottom) in enumerate(pairs, start=1):
            sides = [entrants[top]] + ([] if bottom is None else [entrants[bottom]])
            planned = brackets.PlannedSeries(
                0,
                0,
                brackets.Slot(seed=1),
                brackets.Slot() if bottom is None else brackets.Slot(seed=2),
            )
            row = _row(
                session, stage, round_row, division, sides, [], planned, size, sizes
            )
            row.sequence = sequence
            made.append(row)
    session.flush()
    return made, drew


def on_scored(session: OrmSession, row: CupSeries) -> None:
    """Fill every slot that feeds from this series, and follow the chain down."""
    for other in _fill_below(session, row):
        _settle(session, other)


def _fill_below(session: OrmSession, row: CupSeries) -> Sequence[CupSeries]:
    """Fill every open slot that feeds from this series; answer the series below.

    Every slot below is filled before any series below settles, so a settle
    never reads a slot this series still has to fill as empty.
    """
    below = _downstream(session, ident(row))
    for other in below:
        if other.slot1_from_series_id == row.id and stands_on_side(other, 1) is None:
            other.entrant1_id = entrant_of(row, other.slot1_takes_loser)
            other.player1_id = side_user(row, other.slot1_takes_loser)
        if other.slot2_from_series_id == row.id and stands_on_side(other, 2) is None:
            other.entrant2_id = entrant_of(row, other.slot2_takes_loser)
            other.player2_id = side_user(row, other.slot2_takes_loser)
    session.flush()
    return below


def on_reopened(session: OrmSession, row: CupSeries, force: bool = False) -> None:
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
            other.entrant1_id = None
            other.player1_id = None
        if other.slot2_from_series_id in cleared:
            other.entrant2_id = None
            other.player2_id = None
        other.player1_score = None
        other.player2_score = None
        other.result_kind = "played"
    session.flush()


def after_score(
    session: OrmSession,
    row: CupSeries,
    was_scored: bool,
    was_slot: int | None,
    force: bool = False,
) -> None:
    """Follow a score change into the bracket."""
    _hold_swiss_round(session, row)
    _follow_score(session, row, was_scored, was_slot, force)


def _follow_score(
    session: OrmSession,
    row: CupSeries,
    was_scored: bool,
    was_slot: int | None,
    force: bool = False,
) -> None:
    """Follow a score change into the bracket.

    A correction that turns the series around is a reopen and a fresh score in
    one write: the sides below it move to the new winner and the new loser, and
    a later result is lost, so it takes the same force as a reopen.
    """
    now = scored(row)
    if now and was_scored:
        if was_slot == won_slot(row):
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


def set_result_kind(session: OrmSession, row: CupSeries, data: ResultKindWrite) -> None:
    """Score a series that was not played, and carry its winner downstream."""
    if scored(row):
        raise BadRequestError("This series already carries a result")
    _award(session, row, data.winner == 1, data.result_kind)
    on_scored(session, row)
    _auto_advance(session, row)


def set_places(session: OrmSession, row: CupSeries, data: PlacesWrite) -> None:
    """Write where every side of a lobby finished, and score it as played.

    A lobby plays one game, so its places are its whole result. Once every
    lobby of a round carries places, the round seats the lobbies of the round
    after it from the places that went through.
    """
    series_id = ident(row)
    seats = {side.side_no: side for side in _seats(session, series_id)}
    if not seats:
        raise BadRequestError("This series seats no lobby, so it takes no places")
    for entry in data.places:
        side = seats.get(entry.side_no)
        if side is None:
            raise BadRequestError(f"This lobby seats no side {entry.side_no}")
        side.place = entry.place
    if any(side.place is None for side in seats.values()):
        raise BadRequestError("Every side of the lobby needs a place")
    # A lobby plays one game and its places settle it, so the score only
    # says it was played; the seats carry who finished where
    row.player1_score, row.player2_score = 1, 0
    row.result_kind = "played"
    session.flush()
    _fill_lobbies(session, row)
    _auto_advance(session, row)


def set_sides(session: OrmSession, row: CupSeries, data: LobbySidesWrite) -> None:
    """Seat a free for all lobby again before it is played, in seat order."""
    series_id = ident(row)
    if scored(row):
        raise BadRequestError("This lobby is played, so its seats are settled")
    if not _seats(session, series_id):
        raise BadRequestError("This series seats no lobby, so it takes no sides")
    if len(set(data.entrant_ids)) != len(data.entrant_ids):
        raise BadRequestError("An entrant takes one seat of a lobby, not two")
    if len(data.entrant_ids) < 2:
        raise BadRequestError("A lobby seats two entrants or more")
    stage = _stage_of(session, row)
    entrants = _entrants_by_id(session, data.entrant_ids)
    for entrant_id in data.entrant_ids:
        entrant = entrants.get(entrant_id)
        if entrant is None:
            raise NotFoundError(f"Entrant not found by id: {entrant_id}")
        if stage is not None and entrant.event_id != stage.event_id:
            raise BadRequestError("This entrant does not play in that event")
    _seat(session, row, [entrants[entrant_id] for entrant_id in data.entrant_ids])


def standings_of(event_id: int, stage_id: int) -> list[DivisionStandings]:
    """The table of every division of the stage, from its points and its format."""
    with Session.begin() as session:
        return tables(session, event_id, _stage(session, event_id, stage_id))


def series_of(
    event_id: int, stage_id: int, claims: dict[str, Any] | None = None
) -> CupStagePublic:
    """The rounds of the stage and every series it holds, in drawing order.

    The seed of each side reads null when the event hides its seeds from the caller.
    """
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
            select(CupSeries)
            .options(*CupSeries.eager_options())
            .where(col(CupSeries.round_id).in_(numbers))
        ).all()
        ordered = sorted(held, key=lambda row: _drawn(numbers, row))
        rows = _publics(session, ordered)
        if stage.format is StageFormat.placement:
            by_division: dict[int | None, list[CupSeries]] = {}
            for row in held:
                by_division.setdefault(row.division_id, []).append(row)
            groups: dict[int, tuple[int, int]] = {}
            for division_rows in by_division.values():
                groups |= placement_places(stage, division_rows)[0]
            for public in rows:
                public.place_from, public.place_to = groups.get(public.id, (None, None))
        _fill_sources(
            rows, {ident(row): row.name or f"Round {row.number}" for row in rounds}
        )
        event = session.get(Season, event_id)
        if event is not None and organizers.shows_seeds(claims, event):
            _fill_seeds(rows, ordered)
        return CupStagePublic(
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


def _cup(session: OrmSession, event_id: int) -> Season:
    """The event, which has to be a cup: only a cup's stages are drawn."""
    event = session.get(Season, event_id)
    if event is None:
        raise NotFoundError(f"Event not found by id: {event_id}")
    if event.kind is not EventKind.cup:
        raise BadRequestError("Only a cup's stages are drawn")
    return event


def _seats(session: OrmSession, series_id: int) -> list[CupSeriesSide]:
    """Every seat of one lobby, in seat order."""
    return list(
        session.scalars(
            select(CupSeriesSide)
            .where(col(CupSeriesSide.series_id) == series_id)
            .order_by(col(CupSeriesSide.side_no))
        )
    )


def _seats_of(
    session: OrmSession, series_ids: Sequence[int]
) -> dict[int, list[CupSeriesSide]]:
    """Every seat of every lobby named, keyed by the series, in one read."""
    found: dict[int, list[CupSeriesSide]] = {}
    if not series_ids:
        return found
    for side in session.scalars(
        select(CupSeriesSide)
        .where(col(CupSeriesSide.series_id).in_(series_ids))
        .order_by(col(CupSeriesSide.series_id), col(CupSeriesSide.side_no))
    ):
        found.setdefault(side.series_id, []).append(side)
    return found


def _seat(
    session: OrmSession, row: CupSeries, entrants: Sequence[EventEntrant]
) -> None:
    """Write the seats of one lobby from scratch, in the order they are given."""
    for side in _seats(session, ident(row)):
        session.delete(side)
    session.flush()
    for side_no, entrant in enumerate(entrants, start=1):
        session.add(
            CupSeriesSide(
                series_id=ident(row),
                side_no=side_no,
                user_id=entrant.user_id or 0,
                entrant_id=ident(entrant),
            )
        )
    session.flush()


def _entrants_by_id(
    session: OrmSession, entrant_ids: Sequence[int]
) -> dict[int, EventEntrant]:
    return {
        ident(entrant): entrant
        for entrant in session.scalars(
            select(EventEntrant).where(col(EventEntrant.id).in_(entrant_ids))
        )
    }


def _stage_rows(session: OrmSession, rows: Sequence[CupSeries]) -> list[CupSeries]:
    """Those series read again with the loads of a stage row, in the order
    given: a write answers what the stage read answers."""
    ids = [ident(row) for row in rows]
    read = {
        ident(row): row
        for row in session.scalars(
            select(CupSeries)
            .options(*CupSeries.eager_options())
            .where(col(CupSeries.id).in_(ids))
            .execution_options(populate_existing=True)
        )
    }
    return [read[series_id] for series_id in ids]


def read_one(session: OrmSession, row: CupSeries) -> CupSeriesPublic:
    """One series as its box reads it: the series, its sides and their places."""
    return _publics(session, _stage_rows(session, [row]))[0]


def _publics(session: OrmSession, rows: Sequence[CupSeries]) -> list[CupSeriesPublic]:
    """The boxes of these series, in their order: the rules, the races and the
    MMR of each side, the team behind a team side and every seat."""
    publics = [CupSeriesPublic.from_series(row) for row in rows]
    cup_reads.fill(session, rows, publics)
    _fill_teams(session, publics)
    _fill_sides(session, publics)
    return publics


def _fill_sides(session: OrmSession, rows: Sequence[CupSeriesPublic]) -> None:
    """Name every seat of every lobby in the list, in one read."""
    wanted = [row.id for row in rows]
    if not wanted:
        return
    found: dict[int, list[SeriesSidePublic]] = {}
    for side, user in session.execute(
        select(CupSeriesSide, User)
        .outerjoin(User, col(User.id) == col(CupSeriesSide.user_id))
        .where(col(CupSeriesSide.series_id).in_(wanted))
        .order_by(col(CupSeriesSide.series_id), col(CupSeriesSide.side_no))
    ):
        found.setdefault(side.series_id, []).append(
            SeriesSidePublic(
                side_no=side.side_no,
                user_id=side.user_id or None,
                user=UserSummaryPublic.from_user(user) if user else None,
                entrant_id=side.entrant_id,
                place=side.place,
            )
        )
    for row in rows:
        row.sides = found.get(row.id, [])


def _fill_seeds(rows: Sequence[CupSeriesPublic], held: Sequence[CupSeries]) -> None:
    """Copy the seed of each side from the entrants the series read loaded."""
    for row, series in zip(rows, held, strict=True):
        row.entrant1_seed = series.entrant1.seed if series.entrant1 else None
        row.entrant2_seed = series.entrant2.seed if series.entrant2 else None


def _fill_sources(rows: Sequence[CupSeriesPublic], names: Mapping[int, str]) -> None:
    """Name the series each fed side comes from, such as "Loser of UB R1 M3"."""
    by_id = {row.id: row for row in rows}

    def source(feeder_id: int | None, takes_loser: bool) -> str | None:
        """The label of one side, or None when no series of the read feeds it."""
        feeder = by_id.get(feeder_id or 0)
        if feeder is None:
            return None
        name = (
            names.get(feeder.round_id or 0, "")
            .replace("Upper bracket", "UB")
            .replace("Lower bracket", "LB")
            .replace(" round ", " R")
        )
        label = f"{'Loser' if takes_loser else 'Winner'} of {name}"
        return label if feeder.sequence is None else f"{label} M{feeder.sequence}"

    for row in rows:
        row.slot1_source = source(row.slot1_from_series_id, row.slot1_takes_loser)
        row.slot2_source = source(row.slot2_from_series_id, row.slot2_takes_loser)


def _fill_lobbies(session: OrmSession, row: CupSeries) -> None:
    """Seat the next round's lobbies once every lobby of this one has places.

    The places that go through rank on the place first and the lobby second,
    so every lobby winner sits above every runner-up, and the snake deals them
    over the lobbies of the round after this one.
    """
    stage = _stage_of(session, row)
    if stage is None or stage.format is not StageFormat.ffa:
        return
    rounds = {
        ident(held): place for place, held in enumerate(_rounds_of(session, stage.id))
    }
    place = rounds.get(row.round_id or 0)
    if place is None:
        return
    held = [
        other
        for other in _series_of(session, stage.id)
        if other.division_id == row.division_id
    ]
    done = [other for other in held if rounds.get(other.round_id or 0) == place]
    following = [
        other for other in held if rounds.get(other.round_id or 0) == place + 1
    ]
    if not following or any(not scored(other) for other in done):
        return
    seats = _seats_of(session, [ident(other) for other in following])
    # A round already seated is left alone; only an empty one fills from below
    if any(side.entrant_id for sides in seats.values() for side in sides):
        return
    through = _through(session, stage, done)
    dealt = brackets.snake(len(through), len(following))
    for lobby, taking in zip(following, dealt, strict=True):
        _seat(session, lobby, [through[seed - 1] for seed in taking])


def _through(
    session: OrmSession, stage: EventStage, lobbies: Sequence[CupSeries]
) -> list[EventEntrant]:
    """The entrants the lobbies of one round send on, best place first."""
    top = _lobby_advance(stage, stage.lobby_size or 2)
    seats = _seats_of(session, [ident(lobby) for lobby in lobbies])
    taking = sorted(
        (side.place, order, side.entrant_id)
        for order, lobby in enumerate(lobbies)
        for side in seats.get(ident(lobby), [])
        if side.entrant_id is not None and side.place is not None and side.place <= top
    )
    found = _entrants_by_id(session, [entrant_id for _, _, entrant_id in taking])
    return [found[entrant_id] for _, _, entrant_id in taking if entrant_id in found]


def _lobby_advance(stage: EventStage, seats: int) -> int:
    """How many places of one lobby play on: the stage's `group_advance`, or
    half its seats. `advance_count` stays what the stage carries to the next."""
    return stage.group_advance or max(seats // 2, 1)


def _pay(stage: EventStage) -> list[int]:
    """What each place of a lobby pays, best place first.

    A stage that names no scale counts its seats down, so a lobby of four
    pays 4, 3, 2, 1.
    """
    if stage.points_by_place:
        return [int(word) for word in stage.points_by_place.split(",") if word.strip()]
    return list(range(stage.lobby_size or 1, 0, -1))


def _fill_teams(session: OrmSession, rows: Sequence[CupSeriesPublic]) -> None:
    """Name the team behind every team side, so the box prints it."""
    wanted = {row.entrant1_id for row in rows} | {row.entrant2_id for row in rows}
    wanted.discard(None)
    if not wanted:
        return
    teams = {
        ident(entrant): team_summary(team)
        for entrant, team in session.execute(
            select(EventEntrant, CupTeam)
            .join(CupTeam, col(CupTeam.id) == col(EventEntrant.cup_team_id))
            .where(col(EventEntrant.id).in_(wanted))
        )
    }
    for row in rows:
        row.team1 = teams.get(row.entrant1_id or 0)
        row.team2 = teams.get(row.entrant2_id or 0)


def _drawn(numbers: dict[int, int], row: CupSeries) -> tuple[int, int, int, int]:
    """Where a series is drawn: its round, its division, its place, its id."""
    return (
        numbers.get(row.round_id, 0),
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
    rows: Sequence[CupSeries],
    planned: brackets.PlannedSeries,
    side_size: int = 1,
    sizes: Mapping[int, int] | None = None,
) -> CupSeries:
    """Write one planned series; a padded pair is a walkover for the side it has."""
    if len(planned.slots) > 2:
        return _lobby(session, round_row, division_id, field, planned)
    entrant1, user1, feeder1 = _slot(field, rows, planned.slot1)
    entrant2, user2, feeder2 = _slot(field, rows, planned.slot2)
    # The rosters of this series' own two sides; an undrawn pair takes side_size
    held = [(sizes or {}).get(entrant or 0) for entrant in (entrant1, entrant2)]
    row = CupSeries(
        round_id=ident(round_row),
        division_id=division_id,
        entrant1_id=entrant1,
        entrant2_id=entrant2,
        player1_id=user1,
        player2_id=user2,
        side_size=max([one for one in held if one], default=side_size),
        slot1_from_series_id=feeder1,
        slot1_takes_loser=planned.slot1.takes_loser,
        slot2_from_series_id=feeder2,
        slot2_takes_loser=planned.slot2.takes_loser,
    )
    session.add(row)
    session.flush()
    if feeder1 is None and feeder2 is None and (entrant1 is None) != (entrant2 is None):
        wins = wins_of(round_row.best_of or stage.best_of)
        _award(session, row, entrant1 is not None, "walkover", wins)
    return row


def _lobby(
    session: OrmSession,
    round_row: DBEventRound,
    division_id: int | None,
    field: Sequence[EventEntrant],
    planned: brackets.PlannedSeries,
) -> CupSeries:
    """Write one free for all lobby: one series, one `cup_series_side` row a seat.

    The player columns stay null, so nothing that reads a two-sided series
    reads a lobby by mistake; the seats name who plays it. A seat the plan
    leaves empty waits for the round before it to send its places through.
    """
    row = CupSeries(round_id=ident(round_row), division_id=division_id)
    session.add(row)
    session.flush()
    for side_no, slot in enumerate(planned.slots, start=1):
        entrant, user, _ = _slot(field, [], slot)
        session.add(
            CupSeriesSide(
                series_id=ident(row),
                side_no=side_no,
                user_id=user or 0,
                entrant_id=entrant,
            )
        )
    session.flush()
    return row


def _slot(
    field: Sequence[EventEntrant], rows: Sequence[CupSeries], slot: brackets.Slot
) -> tuple[int | None, int | None, int | None]:
    """The entrant and the user this slot opens with, and the series it takes
    its side from. A team entrant names no user: its roster plays the side."""
    if slot.seed is not None:
        entrant = field[slot.seed - 1]
        return ident(entrant), entrant.user_id, None
    if slot.feeder is not None:
        return None, None, ident(rows[slot.feeder])
    return None, None, None


def _side_sizes(session: OrmSession, field: Sequence[EventEntrant]) -> dict[int, int]:
    """How many players each team entrant of the field fields for the event.

    A field of players answers nothing: a player side holds one. The map is
    keyed by entrant, so each series reads the rosters of its own two sides.
    """
    teams = {entrant.cup_team_id for entrant in field if entrant.cup_team_id}
    if not teams:
        return {}
    rosters = {
        team_id: total
        for team_id, total in session.execute(
            select(col(CupTeamMember.team_id), func.count())
            .where(col(CupTeamMember.team_id).in_(teams))
            .group_by(col(CupTeamMember.team_id))
        )
    }
    return {
        ident(entrant): rosters[entrant.cup_team_id]
        for entrant in field
        if entrant.cup_team_id in rosters
    }


def _award(
    session: OrmSession,
    row: CupSeries,
    to_first: bool,
    kind: str,
    wins: int | None = None,
) -> None:
    """Write a result no game was played for, to one side of the series."""
    maps = wins if wins is not None else series_wins(session, row)
    row.player1_score, row.player2_score = (maps, 0) if to_first else (0, maps)
    row.result_kind = kind
    session.flush()


def _settle(session: OrmSession, row: CupSeries) -> None:
    """A series nobody plays is a walkover: a bye, a double bye, or a reset the
    final settled. A series that a withdrawn entrant stands in is a forfeit."""
    if scored(row):
        return
    final = _reset_final(session, row)
    if final is not None:
        # A bracket reset is played only when the lower bracket side takes the final
        if scored(final) and won_slot(final) == 1:
            _award(session, row, to_first=True, kind="walkover")
            on_scored(session, row)
        return
    first, first_known = _resolved(session, row, 1)
    second, second_known = _resolved(session, row, 2)
    if not (first_known and second_known):
        return
    if first is not None and second is not None:
        _forfeit(session, row, _withdrawn_sides(session, row))
        return
    if first is None and second is None:
        # Two empty sides: a walkover nobody wins; the series below gets an empty side
        row.player1_score = row.player2_score = 0
        row.result_kind = "walkover"
        session.flush()
    else:
        _award(session, row, first is not None, "walkover")
    on_scored(session, row)


def forfeit_open(session: OrmSession, entrant_ids: Sequence[int]) -> int:
    """Settle every open series these withdrawn entrants stand in with both sides
    known, as a forfeit; a series they reach later forfeits when it fills.

    The series below each forfeit fill and settle on, so a withdrawal plays its
    whole way through a bracket at once. Answers the count of forfeits written.
    """
    ids = [entrant_id for entrant_id in entrant_ids if entrant_id is not None]
    if not ids:
        return 0
    rows = session.scalars(
        select(CupSeries)
        .where(
            or_(
                col(CupSeries.entrant1_id).in_(ids),
                col(CupSeries.entrant2_id).in_(ids),
            ),
            col(CupSeries.player1_score).is_(None),
            col(CupSeries.player2_score).is_(None),
        )
        .order_by(col(CupSeries.id))
    ).all()
    written = 0
    for row in rows:
        if scored(row) or row.entrant1_id is None or row.entrant2_id is None:
            continue
        written += _forfeit(session, row, _withdrawn_sides(session, row))
    return written


def _withdrawn_sides(session: OrmSession, row: CupSeries) -> set[int]:
    """The sides of a two-sided series whose entrant has withdrawn."""
    by_side = {1: row.entrant1_id, 2: row.entrant2_id}
    ids = [entrant_id for entrant_id in by_side.values() if entrant_id is not None]
    if not ids:
        return set()
    gone = set(
        session.scalars(
            select(col(EventEntrant.id)).where(
                col(EventEntrant.id).in_(ids),
                col(EventEntrant.withdrawn_at).is_not(None),
            )
        )
    )
    if not gone:
        return set()
    return {side for side, entrant_id in by_side.items() if entrant_id in gone}


def _forfeit(session: OrmSession, row: CupSeries, gone: set[int]) -> int:
    """Settle a series the withdrawn sides give up: the other side wins it, and
    a series both sides left is a forfeit nobody wins. Answers 1 when written."""
    if not gone or scored(row):
        return 0
    if gone == {1, 2}:
        row.player1_score = row.player2_score = 0
        row.result_kind = "forfeit"
        session.flush()
    else:
        _award(session, row, to_first=2 in gone, kind="forfeit")
    on_scored(session, row)
    _auto_advance(session, row)
    return 1


def _reset_final(session: OrmSession, row: CupSeries) -> CupSeries | None:
    """The grand final a bracket reset hangs off, which is the one series it
    takes both its sides from: the winner in front, the loser behind."""
    if (
        row.slot1_from_series_id is None
        or row.slot1_from_series_id != row.slot2_from_series_id
        or row.slot1_takes_loser
        or not row.slot2_takes_loser
    ):
        return None
    return session.get(CupSeries, row.slot1_from_series_id)


def _resolved(
    session: OrmSession, row: CupSeries, slot: int
) -> tuple[int | None, bool]:
    """The side in one slot, which a team side carries as its entrant, and
    whether its feeder has answered at all.

    A scored feeder that sends nobody on, which is the loser of a walkover,
    leaves the slot known and empty.
    """
    side = stands_on_side(row, slot)
    if side is not None:
        return side, True
    feeder_id = row.slot1_from_series_id if slot == 1 else row.slot2_from_series_id
    feeder = session.get(CupSeries, feeder_id) if feeder_id else None
    return None, feeder is not None and scored(feeder)


def _downstream(session: OrmSession, series_id: int) -> Sequence[CupSeries]:
    """Every series that takes one of its sides from this one."""
    return session.scalars(
        select(CupSeries)
        .where(
            or_(
                col(CupSeries.slot1_from_series_id) == series_id,
                col(CupSeries.slot2_from_series_id) == series_id,
            )
        )
        .order_by(col(CupSeries.id))
    ).all()


def _closure(session: OrmSession, row: CupSeries) -> list[CupSeries]:
    """Every series below this one, however far down; each one listed once."""
    found: list[CupSeries] = []
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


def _stage_of(session: OrmSession, row: CupSeries) -> EventStage | None:
    """The stage a series is played in, through the round it belongs to."""
    round_row = session.get(DBEventRound, row.round_id) if row.round_id else None
    if round_row is None or round_row.stage_id is None:
        return None
    return session.get(EventStage, round_row.stage_id)


def previous_stage(
    session: OrmSession, event_id: int, stage: EventStage
) -> EventStage | None:
    """The stage before this one: the table `previous_stage` seeding reads."""
    return session.scalars(
        select(EventStage)
        .where(
            col(EventStage.event_id) == event_id,
            col(EventStage.position) < stage.position,
        )
        .order_by(col(EventStage.position).desc())
    ).first()


def advancing(session: OrmSession, event_id: int, stage: EventStage) -> list[list[int]]:
    """The entrant ids every division of the stage sends on, in its table order.

    The top `advance_count` places go through, or the whole table when the
    stage names no count. A stage that plays groups takes `group_advance` from
    each of them and merges the groups of a division by place, so the winners
    head the list and the draw of the next stage holds them apart. Both
    `advance` and a `previous_stage` seed write read this one order, so the
    unplayed stage is refused here for both of them.
    """
    rows = _series_of(session, stage.id)
    if not rows or any(not scored(row) for row in rows):
        raise BadRequestError("Every series of the stage needs a result first")
    through: dict[int | None, list[tuple[int, int, int]]] = {}
    for table in tables(session, event_id, stage):
        take = (
            stage.group_advance or stage.advance_count
            if table.group_no
            else stage.advance_count
        )
        for place, line in enumerate(
            table.rows[:take] if take else table.rows, start=1
        ):
            through.setdefault(table.division_id, []).append(
                (place, table.group_no or 0, line.entrant_id)
            )
    return [
        [entrant_id for _, _, entrant_id in sorted(lines)] for lines in through.values()
    ]


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


def stage_drawn(session: OrmSession, stage_id: int) -> bool:
    """Whether the stage holds a series, in one short read."""
    return (
        session.scalar(
            select(col(CupSeries.id))
            .join(DBEventRound, col(DBEventRound.id) == col(CupSeries.round_id))
            .where(col(DBEventRound.stage_id) == stage_id)
            .limit(1)
        )
        is not None
    )


def _series_of(session: OrmSession, stage_id: int | None) -> Sequence[CupSeries]:
    """Every series the stage holds, in play order, through its rounds."""
    return session.scalars(
        select(CupSeries)
        .join(DBEventRound, col(DBEventRound.id) == col(CupSeries.round_id))
        .where(col(DBEventRound.stage_id) == stage_id)
        .order_by(col(DBEventRound.number), col(CupSeries.sequence), col(CupSeries.id))
    ).all()


def _rounds_of(session: OrmSession, stage_id: int | None) -> Sequence[DBEventRound]:
    """The rounds the stage already holds, in play order."""
    return session.scalars(
        select(DBEventRound)
        .where(col(DBEventRound.stage_id) == stage_id)
        .order_by(col(DBEventRound.number))
    ).all()


def _next_number(session: OrmSession, event_id: int) -> int:
    """The round number the stage starts at; the rounds of one event are one run."""
    highest = session.scalar(
        select(func.max(col(DBEventRound.number))).where(
            col(DBEventRound.season_id) == event_id
        )
    )
    return (highest or 0) + 1


def _hold_placed(session: OrmSession, event_id: int) -> None:
    """Refuse to draw a cup with divisions while a player stands in none of
    them: the draw plays each division apart, so that player would be left out."""
    held = session.scalar(
        select(col(EventDivision.id))
        .where(col(EventDivision.event_id) == event_id)
        .limit(1)
    )
    if held is None:
        return
    loose = session.scalar(
        select(col(EventEntrant.id))
        .where(
            col(EventEntrant.event_id) == event_id,
            col(EventEntrant.division_id).is_(None),
            col(EventEntrant.withdrawn_at).is_(None),
            col(EventEntrant.waitlisted_at).is_(None),
        )
        .limit(1)
    )
    if loose is not None:
        raise BadRequestError("Place every player in a division first")


def _hold_minimum(
    session: OrmSession, stage: EventStage, fields: dict[int | None, list[EventEntrant]]
) -> None:
    """Refuse to draw the event's first stage with fewer entrants than its minimum.

    The count is every entrant the draw would seat, across the divisions; a
    later stage is seeded from the one before and is never held to it.
    """
    if stage.position != 1:
        return
    event = session.get(Season, stage.event_id)
    least = event.entrant_min if event is not None else None
    seated = sum(len(field) for field in fields.values())
    if least is not None and seated < least:
        raise BadRequestError(
            f"This event is played with at least {least} entrants; {seated} would play"
        )


def _entrants(
    session: OrmSession, event_id: int
) -> dict[int | None, list[EventEntrant]]:
    """Every entrant of every division in seed order; one field without divisions.
    An entrant on a cup's waitlist stands in no field until it is let in."""
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
            col(EventEntrant.waitlisted_at).is_(None),
        )
        .order_by(
            col(EventEntrant.seed).is_(None),
            col(EventEntrant.seed),
            col(EventEntrant.id),
        )
    ).all()
    if not divisions:
        return {None: _one_seat_per_player(entrants)}
    return {
        ident(division): _one_seat_per_player(
            [entrant for entrant in entrants if entrant.division_id == division.id]
        )
        for division in divisions
    }


def _one_seat_per_player(field: Sequence[EventEntrant]) -> list[EventEntrant]:
    """The field with one seat per player, keeping the first row of each.

    An event that takes one entry per race holds a row per race, and the list
    comes in seed order, so the seat is the race the player seeds highest on.
    A team row names no player and stays as it is.
    """
    seats: list[EventEntrant] = []
    seated: set[int] = set()
    for entrant in field:
        if entrant.user_id is not None:
            if entrant.user_id in seated:
                continue
            seated.add(entrant.user_id)
        seats.append(entrant)
    return seats


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
        case StageFormat.placement:
            return brackets.placement_plan(size, stage.placement_lives)
        case StageFormat.round_robin:
            return brackets.round_robin_plan(size, stage.series_per_entrant_per_round)
        case StageFormat.ffa:
            # One lobby that seats the whole field is a league of N series;
            # a field that needs several lobbies plays them off round by round
            seats = stage.lobby_size or size
            if seats >= size:
                return brackets.ffa_league_plan(size, stage.swiss_rounds or 1)
            return brackets.ffa_bracket_plan(size, seats, _lobby_advance(stage, seats))
        case _:
            raise BadRequestError(
                f"This stage plays no format the engine draws: {stage.format.value}"
            )


def _pays_a_bye(stage: EventStage, row: CupSeries) -> bool:
    """Whether the table counts this series although it names one entrant only.

    A stage that draws round by round writes the bye as an awarded one-sided
    series, so it pays its entrant; a planned bracket pads its first round with
    the same shape and pays nothing for it.
    """
    return _draws_by_round(stage) and row.entrant2_id is None


def _draws_by_round(stage: EventStage) -> bool:
    """Whether the stage draws one round at a time instead of planning every
    series up front: it pairs the next round from the table as it stands."""
    return stage.format in BY_ROUND


def _ranking(stage: EventStage) -> list[str]:
    """The tie breaks the stage's table reads, in the order ranking_rule names.

    The words are points, buchholz, game_diff and head_to_head, and a word the
    rule leaves out is not read at all. A stage that draws round by round ranks
    on Buchholz, the sum of the opponents' points, so it reads that order where
    it names no rule of its own.
    """
    rule = stage.ranking_rule
    if _draws_by_round(stage) and rule == RANKING_RULE:
        rule = SWISS_RANKING_RULE
    return [word.strip() for word in rule.split(",") if word.strip()]


def tables(
    session: OrmSession, event_id: int, stage: EventStage
) -> list[DivisionStandings]:
    """One table per division, from the series the stage holds.

    The field of a table is the entrants its own series play over, so the table
    of a finished stage keeps everyone that played it after `advance` has
    reseeded the event for the next stage.
    """
    played: dict[int | None, list[CupSeries]] = {}
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
    seats = _seats_of(session, [ident(row) for rows in played.values() for row in rows])
    tables: list[DivisionStandings] = []
    for division_id, everybody in everyone.items():
        rows = played.get(division_id, [])
        field = _sides_of(everybody, rows, seats) or seeds.get(division_id, [])
        for group_no, group in _split(stage, field):
            tables.append(
                DivisionStandings(
                    division_id=division_id,
                    division_name=names.get(division_id) if division_id else None,
                    group_no=group_no,
                    group_name=None if group_no is None else _group_name(group_no),
                    rows=_table(session, stage, group, rows, seats),
                )
            )
    return tables


def _draws(
    session: OrmSession,
    stage: EventStage,
    fields: Sequence[tuple[int | None, list[EventEntrant]]],
) -> list[tuple[int | None, list[EventEntrant]]]:
    """The fields a generate draws, in order: one per division, or one per group.

    A group is stamped on its entrants, so the tables, the advance and the
    entrants page read the split off the rows and no series carries a group.
    """
    if not _has_groups(stage):
        return list(fields)
    draws: list[tuple[int | None, list[EventEntrant]]] = []
    for division_id, field in fields:
        for number, group in enumerate(
            brackets.snake_groups(field, stage.group_size or 2), start=1
        ):
            for entrant in group:
                entrant.group_no = number
            draws.append((division_id, group))
    session.flush()
    return draws


def _split(
    stage: EventStage, field: Sequence[EventEntrant]
) -> list[tuple[int | None, list[EventEntrant]]]:
    """One field per group where the stage plays them, or the whole division."""
    numbers = sorted({entrant.group_no for entrant in field if entrant.group_no})
    if not _has_groups(stage) or not numbers:
        return [(None, list(field))]
    return [
        (number, [entrant for entrant in field if entrant.group_no == number])
        for number in numbers
    ]


def _has_groups(stage: EventStage) -> bool:
    """Whether the stage splits each division into groups of its own table.

    The groups merge at the next stage, so they are a table format only: a
    stage that plans a bracket plays its division whole.
    """
    return stage.group_size is not None and stage.format is StageFormat.round_robin


def _group_name(number: int) -> str:
    """What a group is called: Group A is the first one of its division."""
    return f"Group {chr(ord('A') + number - 1)}" if number <= 26 else f"Group {number}"


def _sides_of(
    field: Sequence[EventEntrant],
    series: Sequence[CupSeries],
    seats: dict[int, list[CupSeriesSide]],
) -> list[EventEntrant]:
    """The entrants of the division that stand in one of its series, in seed order."""
    sides = {row.entrant1_id for row in series} | {row.entrant2_id for row in series}
    sides |= {side.entrant_id for row in series for side in seats.get(ident(row), [])}
    sides.discard(None)
    return [entrant for entrant in field if ident(entrant) in sides]


def _table(
    session: OrmSession,
    stage: EventStage,
    field: Sequence[EventEntrant],
    series: Sequence[CupSeries],
    seats: dict[int, list[CupSeriesSide]] | None = None,
) -> list[StandingRow]:
    """One division's places, from the stage's points and the format it plays.

    Every line keys on the entrant, so a team side counts as one line and the
    user behind a solo side rides along.
    """
    entrants = {ident(entrant): entrant for entrant in field}
    order = list(entrants)
    if stage.format is StageFormat.ffa:
        return _place_table(session, stage, entrants, series, seats or {})
    results = [
        (
            row.entrant1_id,
            row.entrant2_id,
            row.player1_score or 0,
            row.player2_score or 0,
        )
        for row in series
        if scored(row)
        and row.entrant1_id in entrants
        and (row.entrant2_id in entrants or _pays_a_bye(stage, row))
    ]
    table = brackets.standings(
        order,
        results,
        brackets.Points(
            stage.points_series_won, stage.points_series_drawn, stage.points_game_won
        ),
        _ranking(stage),
    )
    if stage.format is StageFormat.placement:
        return _placement_table(session, stage, entrants, table, results, series)
    if stage.format in BRACKETS:
        reached = _reached(session, stage, order, series)
        table = sorted(table, key=lambda line: reached[line.entrant], reverse=True)
    counted = _counted(order, results)
    names = _names(session, list(entrants.values()))
    return [
        StandingRow(
            position=place,
            entrant_id=line.entrant,
            user_id=entrants[line.entrant].user_id,
            team_id=entrants[line.entrant].cup_team_id,
            name=names.get(line.entrant),
            points=line.points,
            game_diff=line.game_diff,
            **counted[line.entrant],
        )
        for place, line in enumerate(table, start=1)
    ]


def _place_table(
    session: OrmSession,
    stage: EventStage,
    entrants: dict[int, EventEntrant],
    series: Sequence[CupSeries],
    seats: dict[int, list[CupSeriesSide]],
) -> list[StandingRow]:
    """A free for all table: the place points every entrant took, best first."""
    placings = [
        (side.entrant_id, side.place)
        for row in series
        for side in seats.get(ident(row), [])
        if side.entrant_id in entrants and side.place is not None
    ]
    table = brackets.place_standings(list(entrants), placings, _pay(stage))
    counted = _counted_places(list(entrants), placings)
    names = _names(session, list(entrants.values()))
    return [
        StandingRow(
            position=place,
            entrant_id=line.entrant,
            user_id=entrants[line.entrant].user_id,
            team_id=entrants[line.entrant].cup_team_id,
            name=names.get(line.entrant),
            points=line.points,
            **counted[line.entrant],
        )
        for place, line in enumerate(table, start=1)
    ]


def _counted_places(
    order: Sequence[int], placings: Sequence[tuple[int, int]]
) -> dict[int, dict[str, int]]:
    """Lobbies played and lobbies won per entrant; a lobby counts no games."""
    tally = {
        entrant: {"played": 0, "won": 0, "lost": 0, "games_won": 0, "games_lost": 0}
        for entrant in order
    }
    for entrant, place in placings:
        tally[entrant]["played"] += 1
        tally[entrant]["won" if place == 1 else "lost"] += 1
    return tally


def _reached(
    session: OrmSession,
    stage: EventStage,
    order: Sequence[int],
    series: Sequence[CupSeries],
) -> dict[int, tuple[int, int]]:
    """How far each entrant went: the last round he stood in, then his wins.

    The third place series is drawn in the final round but decides places 3
    and 4, so it counts as a win and never as depth: the two it sends down
    stay at the semi-final they lost, below the runner up.
    """
    numbers = {
        round_row.id: round_row.number
        for round_row in session.scalars(
            select(DBEventRound).where(
                col(DBEventRound.id).in_({row.round_id for row in series})
            )
        )
    }
    third = _third_place(stage, numbers, series)
    depth = dict.fromkeys(order, 0)
    won = dict.fromkeys(order, 0)
    for row in series:
        if row is not third:
            for side in (row.entrant1_id, row.entrant2_id):
                if side in depth:
                    depth[side] = max(depth[side], numbers.get(row.round_id, 0))
        winner = entrant_of(row)
        if winner in won:
            won[winner] += 1
    return {entrant: (depth[entrant], won[entrant]) for entrant in order}


def placement_places(
    stage: EventStage, rows: Sequence[CupSeries]
) -> tuple[dict[int, tuple[int, int]], dict[int, tuple[int, int]]]:
    """The places of one placement bracket: the group of each series, by
    series id, and the places of each entrant, by entrant id.

    The plan follows from the field and the stage's lives, so it is drawn
    again over the series in the order the draw wrote them. An entrant whose
    run has ended holds the places of the group it ended in; one still
    playing holds the group of the latest series it stands in.
    """
    ordered = sorted(rows, key=ident)
    field = {
        side
        for row in ordered
        for side in (row.entrant1_id, row.entrant2_id)
        if side is not None
    }
    if len(field) < 2:
        return {}, {}
    plan = brackets.placement_plan(len(field), stage.placement_lives)
    if len(plan.series) != len(ordered):
        return {}, {}
    groups = {
        ident(row): places for row, places in zip(ordered, plan.places, strict=True)
    }
    held: dict[int, tuple[int, int]] = {}
    for row in ordered:
        for side in (row.entrant1_id, row.entrant2_id):
            if side is not None:
                held[side] = groups[ident(row)]
    for group in plan.finish:
        for slot in group.slots:
            if slot.feeder is None or not scored(ordered[slot.feeder]):
                continue
            entrant = entrant_of(ordered[slot.feeder], slot.takes_loser)
            if entrant is not None:
                held[entrant] = (group.first, group.last)
    return groups, held


def _placement_table(
    session: OrmSession,
    stage: EventStage,
    entrants: dict[int, EventEntrant],
    table: Sequence[brackets.Standing[int]],
    results: Sequence[tuple[int, int | None, int, int]],
    series: Sequence[CupSeries],
) -> list[StandingRow]:
    """A placement bracket's table: every entrant at the first place its run
    holds, so a group that stopped shares one place, and the points order the
    entrants inside it."""
    _, held = placement_places(stage, series)
    after = len(entrants) + 1
    lines = sorted(
        enumerate(table),
        key=lambda pair: (held.get(pair[1].entrant, (after,))[0], pair[0]),
    )
    counted = _counted(list(entrants), results)
    names = _names(session, list(entrants.values()))
    return [
        StandingRow(
            position=held[line.entrant][0] if held else place,
            entrant_id=line.entrant,
            user_id=entrants[line.entrant].user_id,
            team_id=entrants[line.entrant].cup_team_id,
            name=names.get(line.entrant),
            points=line.points,
            game_diff=line.game_diff,
            **counted[line.entrant],
        )
        for place, (_, line) in enumerate(lines, start=1)
        if not held or line.entrant in held
    ]


def _third_place(
    stage: EventStage, numbers: dict[int | None, int], series: Sequence[CupSeries]
) -> CupSeries | None:
    """The series of the last round both beaten semi-finalists play, if it is drawn."""
    if not stage.third_place or stage.format is not StageFormat.single_elimination:
        return None
    last = max(numbers.values(), default=0)
    return next(
        (
            row
            for row in series
            if numbers.get(row.round_id) == last
            and row.slot1_takes_loser
            and row.slot2_takes_loser
        ),
        None,
    )


def _counted(
    order: Sequence[int], results: Sequence[tuple[int, int | None, int, int]]
) -> dict[int, dict[str, int]]:
    """CupSeries played, won and lost, and the games either way, per entrant."""
    tally = {
        entrant: {"played": 0, "won": 0, "lost": 0, "games_won": 0, "games_lost": 0}
        for entrant in order
    }
    for first, second, first_games, second_games in results:
        for own, other, games, other_games in (
            (first, second, first_games, second_games),
            (second, first, second_games, first_games),
        ):
            if own is None:
                continue
            tally[own]["played"] += 1
            tally[own]["games_won"] += games
            tally[own]["games_lost"] += other_games
            if games > other_games:
                tally[own]["won"] += 1
            elif games < other_games:
                tally[own]["lost"] += 1
    return tally


def _names(session: OrmSession, field: Sequence[EventEntrant]) -> dict[int, str | None]:
    """The name of every entrant in the table: the player, or the team."""
    if not field:
        return {}
    users = {
        ident(user): user.name
        for user in session.scalars(
            select(User).where(
                col(User.id).in_({row.user_id for row in field if row.user_id})
            )
        )
    }
    wanted = {row.cup_team_id for row in field if row.cup_team_id}
    teams = (
        {
            ident(team): team.name
            for team in session.scalars(
                select(CupTeam).where(col(CupTeam.id).in_(wanted))
            )
        }
        if wanted
        else {}
    )
    return {
        ident(row): teams.get(row.cup_team_id)
        if row.cup_team_id
        else users.get(row.user_id)
        for row in field
    }


def _auto_advance(session: OrmSession, row: CupSeries) -> None:
    """A stage that carries its places forward does it on the last result.

    A stage played straight away plays on by itself: the last result of a
    Swiss round draws the next round while the stage has rounds left, and a
    stage that ends seeds the one after it and draws it at once. A Swiss stage
    with rounds left never carries its places forward.
    """
    stage = _stage_of(session, row)
    swiss = stage is not None and stage.format is StageFormat.swiss
    if stage is None or not (swiss or stage.auto_advance):
        return
    played = _series_of(session, stage.id)
    if any(not scored(other) for other in played):
        return
    cup = _plays_on_by_itself(stage)
    if swiss and _rounds_left(session, stage, played):
        if cup:
            _draw_round(session, stage.event_id, ident(stage))
        return
    if not stage.auto_advance:
        return
    following = _next_stage(session, stage.event_id, stage)
    if following is None:
        return
    _advance(session, stage.event_id, stage)
    if cup and not _draws_by_round(following) and not _series_of(session, following.id):
        _generate(session, stage.event_id, ident(following))


def _plays_on_by_itself(stage: EventStage) -> bool:
    """Whether the stage plays on by itself: every series of it is played
    straight away, as a cup's evening is, so its rounds and the stage after it
    draw themselves. The stage decides, never the kind of its event."""
    return stage.scheduling_mode is SchedulingMode.immediate


def _round_limit(stage: EventStage, field: int) -> int | None:
    """The rounds a Swiss stage plays over a field of this size: the rounds it
    names, cut to the rounds the field holds without a pairing twice."""
    if stage.swiss_rounds is None:
        return None
    most = field if field % 2 else field - 1
    return max(1, min(stage.swiss_rounds, most))


def _rounds_left(
    session: OrmSession, stage: EventStage, played: Sequence[CupSeries]
) -> bool:
    """Whether a Swiss stage still has a round to draw for its field."""
    fields = _fields(_entrants(session, stage.event_id))
    drawn = len({row.round_id for row in played})
    return any(
        (limit := _round_limit(stage, len(field))) is not None and drawn < limit
        for field in fields.values()
    )


def _hold_swiss_round(session: OrmSession, row: CupSeries) -> None:
    """Refuse a result change in a Swiss round once a later round is drawn:
    that round's pairings were made from the table this result is part of.
    A series that names no entrant is no Swiss pairing, so it reads nothing."""
    if row.entrant1_id is None and row.entrant2_id is None:
        return
    stage = _stage_of(session, row)
    if stage is None or stage.format is not StageFormat.swiss:
        return
    if not _plays_on_by_itself(stage):
        return
    rounds = list(_rounds_of(session, ident(stage)))
    numbers = {ident(round_row): round_row.number for round_row in rounds}
    mine = numbers.get(row.round_id)
    if mine is not None and any(number > mine for number in numbers.values()):
        raise BadRequestError(
            "The next round is drawn from this result, so it stays as it is"
        )


def _advance(session: OrmSession, event_id: int, stage: EventStage) -> int:
    """Seed the top places of every division; the rest lose their seed."""
    carried: set[int] = set()
    for division in advancing(session, event_id, stage):
        for place, entrant_id in enumerate(division, start=1):
            entrant = session.get(EventEntrant, entrant_id)
            if entrant is None:
                continue
            entrant.seed = place
            entrant.seed_source = "previous_stage"
            carried.add(entrant_id)
    for entrant in session.scalars(
        select(EventEntrant).where(col(EventEntrant.event_id) == event_id)
    ):
        if ident(entrant) not in carried:
            entrant.seed = None
    session.flush()
    return len(carried)


def is_cup(event_id: int) -> bool:
    """Whether the event is a cup, whose stages read the cup's own tables."""
    with Session.begin() as session:
        event = session.get(Season, event_id)
        return event is not None and event.kind is EventKind.cup
