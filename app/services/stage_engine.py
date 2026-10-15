"""Follow the results of the `series` table into its stage: KOTH and GNL.

A cup draws, plays and ranks its stages on its own tables in
app.services.cup_engine; this engine keeps what a KOTH night and a GNL season
reach on `series`. A result moves the KOTH crown and fills a chain the admin
grows one challenger at a time, and a stage read answers the night's series
and its table. A series with no feeders answers nothing when it is scored or
reopened, so every GNL payload holds, and the engine never branches on the
kind of an event.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core import brackets
from app.core.db import Session
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.outcome import entrant_of, scored, side_user, stands_on_side, won_slot
from app.core.scoring import wins_of
from app.models.base import ident
from app.models.enums import StageFormat
from app.models.event_division import EventDivision
from app.models.event_entrant import EventEntrant
from app.models.event_stage import (
    RANKING_RULE,
    SWISS_RANKING_RULE,
    DivisionStandings,
    EventStage,
    StandingRow,
)
from app.models.koth_crown_event import KothCrownEvent
from app.models.relationships import DBEventRound, EventRoundPublic
from app.models.season import Season
from app.models.series import (
    ResultKindWrite,
    Series,
    StageSeriesPublic,
    StageSeriesRow,
)
from app.models.series_game import DBSeriesGame
from app.models.series_side import SeriesSide, SeriesSidePublic
from app.models.team import Team
from app.models.team_summary import TeamSummaryPublic
from app.models.user import User, UserSummaryPublic
from app.services import derived, organizers
from app.services.series_rules import series_rules

# The formats whose last round is the final, so every division ends together
BRACKETS = (
    StageFormat.single_elimination,
    StageFormat.double_elimination,
    StageFormat.placement,
)
# The formats that draw one round at a time, from the table as it stands
BY_ROUND = (StageFormat.swiss,)


def series_wins(session: OrmSession, row: Series) -> int:
    """The maps a win takes, from the best-of the series plays under."""
    return wins_of(series_rules(session, row).best_of)


def append_to_chain(
    session: OrmSession,
    stage: EventStage,
    division: EventDivision | None,
    entrant: EventEntrant,
) -> Series:
    """Write one more series at the end of a division's chain.

    The stage qualifies by the shape it plans, never by the kind of its event:
    a format that plans as a chain grows this way and every other one refuses.
    An event that runs no divisions passes none and grows its one chain. A
    closed event grows no chain, and a player a series of the chain already
    names takes no second seat in it.
    """
    if not _plans_as_chain(stage):
        raise BadRequestError("This stage plays no chain, so it takes no challenger")
    event = session.get(Season, stage.event_id)
    if event is not None and event.closed_at is not None:
        raise BadRequestError("The event is closed")
    division_id = ident(division) if division else None
    if entrant.event_id != stage.event_id or entrant.division_id != division_id:
        raise BadRequestError("This entrant does not play in that division")
    chain = [
        row for row in _series_of(session, stage.id) if row.division_id == division_id
    ]
    if not chain:
        raise BadRequestError(
            "The chain holds no series yet; two entrants open it before a third joins"
        )
    playing = {row.player1_id for row in chain} | {row.player2_id for row in chain}
    if entrant.user_id is not None and entrant.user_id in playing:
        raise BadRequestError("This player already plays in that chain")
    last = chain[-1]
    round_row = session.get(DBEventRound, last.round_id)
    if round_row is None:
        raise BadRequestError("The chain has no round to play in")
    row = _row(
        session,
        stage,
        round_row,
        division_id,
        [entrant],
        [last],
        brackets.PlannedSeries(0, 0, brackets.Slot(feeder=0), brackets.Slot(seed=1)),
        last.side_size,
    )
    row.sequence = (last.sequence or len(chain)) + 1
    session.flush()
    # A chain the king already leads fills the new front side at once
    if scored(last):
        on_scored(session, last)
    return row


def add_challenger(event_id: int, stage_id: int, entrant_id: int) -> StageSeriesRow:
    """Append one entrant to the end of the chain his division plays."""
    with Session.begin() as session:
        stage = _stage(session, event_id, stage_id)
        entrant = session.get(EventEntrant, entrant_id)
        if entrant is None or entrant.event_id != event_id:
            raise NotFoundError(f"Entrant not found by id: {entrant_id}")
        division = (
            session.get(EventDivision, entrant.division_id)
            if entrant.division_id
            else None
        )
        added = append_to_chain(session, stage, division, entrant)
        public = StageSeriesRow.from_series(_stage_rows(session, [added])[0])
        events = derived.fill_series(session, [public])
        _fill_teams(session, [public])
        derived.fill_mmrs(session, [public], events)
        _fill_sides(session, [public])
        return public


def on_scored(session: OrmSession, row: Series) -> None:
    """Fill every slot that feeds from this series, and follow the chain down."""
    for other in _fill_below(session, row):
        _settle(session, other)


def _fill_below(session: OrmSession, row: Series) -> Sequence[Series]:
    """Fill every open slot that feeds from this series; answer the series below.

    Every slot below is filled before any series below settles, so a settle
    never reads a slot this series still has to fill as empty.
    """
    below = _downstream(session, ident(row))
    for other in below:
        filled = False
        if other.slot1_from_series_id == row.id and _open(other, 1):
            other.entrant1_id = entrant_of(row, other.slot1_takes_loser)
            other.player1_id = side_user(row, other.slot1_takes_loser)
            filled = not _open(other, 1)
        if other.slot2_from_series_id == row.id and _open(other, 2):
            other.entrant2_id = entrant_of(row, other.slot2_takes_loser)
            other.player2_id = side_user(row, other.slot2_takes_loser)
            filled = filled or not _open(other, 2)
        if filled and other.host_player_id == 0:
            other.host_player_id = other.player1_id or 0
    session.flush()
    return below


def _open(row: Series, slot: int) -> bool:
    """Whether a slot still waits: neither its entrant nor its player is named."""
    return stands_on_side(row, slot) is None


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
            other.entrant1_id = None
            other.player1_id = None
        if other.slot2_from_series_id in cleared:
            other.entrant2_id = None
            other.player2_id = None
        other.player1_score = None
        other.player2_score = None
        other.result_kind = "played"
        game_one(session, other)
    session.flush()


def after_score(
    session: OrmSession,
    row: Series,
    was_scored: bool,
    was_slot: int | None,
    force: bool = False,
) -> None:
    """Follow a score change into the bracket and move the crown behind it."""
    game_one(session, row)
    _follow_score(session, row, was_scored, was_slot, force)
    # Only a save that changes who won moves the crown
    if not was_scored or was_slot != won_slot(row):
        crown(session, row)


def game_one(session: OrmSession, row: Series) -> None:
    """A koth series is one map, so its game 1 carries the series winner."""
    stage = _stage_of(session, row)
    if stage is None or stage.format is not StageFormat.koth:
        return
    game = session.get(DBSeriesGame, (ident(row), 1))
    slot = won_slot(row)
    if game is None:
        if slot is None:
            return
        game = DBSeriesGame(series_id=ident(row), game_no=1)
        session.add(game)
    game.winner_side = {1: "A", 2: "B"}.get(slot)


def crown(session: OrmSession, row: Series) -> None:
    """Move the crown of a koth division behind this result.

    An empty throne is taken by the winner, and the reigning king keeps the
    crown until he plays and loses: a side game between two other entrants
    leaves it where it stands. Turning a result around moves it back, because
    the king the old result crowned is one of the two sides.
    """
    if not scored(row) or row.division_id is None:
        return
    stage = _stage_of(session, row)
    if stage is None or stage.format is not StageFormat.koth:
        return
    division = session.get(EventDivision, row.division_id)
    winner = entrant_of(row)
    if division is None or winner is None:
        return
    wearer = (
        session.get(EventEntrant, division.king_entrant_id)
        if division.king_entrant_id is not None
        else None
    )
    # A wearer who is gone, left or now in another bracket is an empty throne
    if (
        wearer is None
        or wearer.withdrawn_at is not None
        or wearer.division_id != row.division_id
        or wearer.user_id in (row.player1_id, row.player2_id)
    ):
        division.king_entrant_id = winner
        session.flush()


def uncrown(session: OrmSession, entrant_ids: Sequence[int]) -> None:
    """Empty every throne these rows wear: a row that leaves loses the crown.

    Only a koth division wears a crown, and each emptied throne is a crown
    event, since no result shows it.
    """
    ids = [entrant_id for entrant_id in entrant_ids if entrant_id is not None]
    if not ids:
        return
    worn = session.scalars(
        select(EventDivision).where(col(EventDivision.king_entrant_id).in_(ids))
    )
    for division in list(worn):
        division.king_entrant_id = None
        crown_event(session, division, None)
    session.flush()


def crown_event(
    session: OrmSession, division: EventDivision, entrant_id: int | None
) -> None:
    """Record a crown change no result shows, after the bracket's newest result."""
    after = session.scalar(
        select(func.max(Series.sequence)).where(
            col(Series.division_id) == ident(division),
            or_(
                col(Series.player1_score).is_not(None),
                col(Series.player2_score).is_not(None),
            ),
        )
    )
    session.add(
        KothCrownEvent(
            division_id=ident(division),
            after_sequence=after or 0,
            entrant_id=entrant_id,
        )
    )


def _follow_score(
    session: OrmSession,
    row: Series,
    was_scored: bool,
    was_slot: int | None,
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
        if was_slot == won_slot(row):
            return
        on_reopened(session, row, force)
        on_scored(session, row)
        return
    if now == was_scored:
        return
    if now:
        on_scored(session, row)
    else:
        on_reopened(session, row, force)


def set_result_kind(series_id: int, data: ResultKindWrite) -> None:
    """Score a series that was not played, and carry its winner downstream."""
    with Session.begin() as session:
        row = session.get(Series, series_id)
        if row is None:
            raise NotFoundError("Series not found")
        if scored(row):
            raise BadRequestError("This series already carries a result")
        _award(session, row, data.winner == 1, data.result_kind)
        on_scored(session, row)
        crown(session, row)


def standings_of(event_id: int, stage_id: int) -> list[DivisionStandings]:
    """The table of every division of the stage, from its points and its format."""
    with Session.begin() as session:
        return tables(session, event_id, _stage(session, event_id, stage_id))


def series_of(
    event_id: int, stage_id: int, claims: dict[str, Any] | None = None
) -> StageSeriesPublic:
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
            select(Series)
            .options(*Series._list_eager_options())
            .where(col(Series.round_id).in_(numbers))
        ).all()
        ordered = sorted(held, key=lambda row: _drawn(numbers, row))
        rows = [StageSeriesRow.from_series(row) for row in ordered]
        events = derived.fill_series(session, rows)
        _fill_teams(session, rows)
        derived.fill_mmrs(session, rows, events)
        _fill_sides(session, rows)
        _fill_sources(
            rows, {ident(row): row.name or f"Round {row.number}" for row in rounds}
        )
        event = session.get(Season, event_id)
        if event is not None and organizers.shows_seeds(claims, event):
            _fill_seeds(rows, ordered)
        return StageSeriesPublic(
            rounds=[EventRoundPublic.from_row(row) for row in rounds], series=rows
        )


def _seats_of(
    session: OrmSession, series_ids: Sequence[int]
) -> dict[int, list[SeriesSide]]:
    """Every seat of every lobby named, keyed by the series, in one read."""
    found: dict[int, list[SeriesSide]] = {}
    if not series_ids:
        return found
    for side in session.scalars(
        select(SeriesSide)
        .where(col(SeriesSide.series_id).in_(series_ids))
        .order_by(col(SeriesSide.series_id), col(SeriesSide.side_no))
    ):
        found.setdefault(side.series_id, []).append(side)
    return found


def _stage_rows(session: OrmSession, rows: Sequence[Series]) -> list[Series]:
    """Those series read again with the loads of a stage row, in the order
    given: a write answers what the stage read answers."""
    ids = [ident(row) for row in rows]
    read = {
        ident(row): row
        for row in session.scalars(
            select(Series)
            .options(*Series._list_eager_options())
            .where(col(Series.id).in_(ids))
            .execution_options(populate_existing=True)
        )
    }
    return [read[series_id] for series_id in ids]


def _fill_sides(session: OrmSession, rows: Sequence[StageSeriesRow]) -> None:
    """Name every seat of every lobby in the list, in one read."""
    wanted = [row.id for row in rows]
    if not wanted:
        return
    found: dict[int, list[SeriesSidePublic]] = {}
    for side, user in session.execute(
        select(SeriesSide, User)
        .outerjoin(User, col(User.id) == col(SeriesSide.user_id))
        .where(col(SeriesSide.series_id).in_(wanted))
        .order_by(col(SeriesSide.series_id), col(SeriesSide.side_no))
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


def _fill_seeds(rows: Sequence[StageSeriesRow], held: Sequence[Series]) -> None:
    """Copy the seed of each side from the entrants the series read loaded."""
    for row, series in zip(rows, held, strict=True):
        row.entrant1_seed = series.entrant1.seed if series.entrant1 else None
        row.entrant2_seed = series.entrant2.seed if series.entrant2 else None


def _fill_sources(rows: Sequence[StageSeriesRow], names: Mapping[int, str]) -> None:
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


def _fill_teams(session: OrmSession, rows: Sequence[StageSeriesRow]) -> None:
    """Name the team behind every team side, so the box prints it."""
    wanted = {row.entrant1_id for row in rows} | {row.entrant2_id for row in rows}
    wanted.discard(None)
    if not wanted:
        return
    teams = {
        ident(entrant): TeamSummaryPublic.from_team(team)
        for entrant, team in session.execute(
            select(EventEntrant, Team)
            .join(Team, col(Team.id) == col(EventEntrant.team_id))
            .where(col(EventEntrant.id).in_(wanted))
        )
    }
    for row in rows:
        row.team1 = teams.get(row.entrant1_id or 0)
        row.team2 = teams.get(row.entrant2_id or 0)


def _drawn(numbers: dict[int, int], row: Series) -> tuple[int, int, int, int, int]:
    """Where a series is drawn: its round, its division, its fixture, its
    place, its id. A loose series carries no fixture and sorts before one."""
    return (
        numbers.get(row.round_id or 0, 0),
        row.division_id or 0,
        row.match_id or 0,
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
    side_size: int = 1,
    sizes: Mapping[int, int] | None = None,
) -> Series:
    """Write one planned series; a padded pair is a walkover for the side it has."""
    entrant1, user1, feeder1 = _slot(field, rows, planned.slot1)
    entrant2, user2, feeder2 = _slot(field, rows, planned.slot2)
    # The rosters of this series' own two sides; an undrawn pair takes side_size
    held = [(sizes or {}).get(entrant or 0) for entrant in (entrant1, entrant2)]
    row = Series(
        round_id=ident(round_row),
        division_id=division_id,
        host_player_id=user1 or 0,
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


def _slot(
    field: Sequence[EventEntrant], rows: Sequence[Series], slot: brackets.Slot
) -> tuple[int | None, int | None, int | None]:
    """The entrant and the user this slot opens with, and the series it takes
    its side from. A team entrant names no user: its roster plays the side."""
    if slot.seed is not None:
        entrant = field[slot.seed - 1]
        return ident(entrant), entrant.user_id, None
    if slot.feeder is not None:
        return None, None, ident(rows[slot.feeder])
    return None, None, None


def _settle(session: OrmSession, row: Series) -> None:
    """A series nobody plays is a walkover: a bye, a double bye, or a reset the
    final settled."""
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
        return
    if first is None and second is None:
        # Two empty sides: a walkover nobody wins; the series below gets an empty side
        row.player1_score = row.player2_score = 0
        row.result_kind = "walkover"
        session.flush()
    else:
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
    """The side in one slot, which a team side carries as its entrant, and
    whether its feeder has answered at all.

    A scored feeder that sends nobody on, which is the loser of a walkover,
    leaves the slot known and empty.
    """
    side = stands_on_side(row, slot)
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


def _series_of(session: OrmSession, stage_id: int | None) -> Sequence[Series]:
    """Every series the stage holds, in play order, through its rounds."""
    return session.scalars(
        select(Series)
        .join(DBEventRound, col(DBEventRound.id) == col(Series.round_id))
        .where(col(DBEventRound.stage_id) == stage_id)
        .order_by(col(DBEventRound.number), col(Series.sequence), col(Series.id))
    ).all()


def _rounds_of(session: OrmSession, stage_id: int | None) -> Sequence[DBEventRound]:
    """The rounds the stage already holds, in play order."""
    return session.scalars(
        select(DBEventRound)
        .where(col(DBEventRound.stage_id) == stage_id)
        .order_by(col(DBEventRound.number))
    ).all()


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
        case StageFormat.koth:
            return brackets.koth_chain(size)
        case _:
            raise BadRequestError(
                f"This stage plays no format the engine draws: {stage.format.value}"
            )


def _plans_as_chain(stage: EventStage) -> bool:
    """Whether the stage plans as a chain: one round where every series after
    the first takes its front side from the one before it."""
    try:
        plan = _plan(stage, 3)
    except BadRequestError:
        return False
    return len(plan.rounds) == 1 and [
        (planned.slot1.feeder, planned.slot2.seed) for planned in plan.series
    ] == [(None, 2), (0, 3)]


def _pays_a_bye(stage: EventStage, row: Series) -> bool:
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
    series: Sequence[Series],
    seats: dict[int, list[SeriesSide]],
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
    series: Sequence[Series],
    seats: dict[int, list[SeriesSide]] | None = None,
) -> list[StandingRow]:
    """One division's places, from the stage's points and the format it plays.

    Every line keys on the entrant, so a team side counts as one line and the
    user behind a solo side rides along.
    """
    entrants = {ident(entrant): entrant for entrant in field}
    king = _king(session, field, series) if stage.format is StageFormat.koth else None
    # A king crowned by hand who played nothing still holds place one
    if king is not None:
        entrants.setdefault(ident(king), king)
    order = list(entrants)
    first = 1
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
    if stage.format in BRACKETS:
        reached = _reached(session, stage, order, series)
        table = sorted(table, key=lambda line: reached[line.entrant], reverse=True)
    elif stage.format is StageFormat.koth:
        crowned = ident(king) if king is not None else None
        played = {
            side
            for row in series
            if scored(row)
            for side in (row.entrant1_id, row.entrant2_id)
        }
        # Place one is the king's; besides him only a row that played is placed
        table = sorted(
            (
                line
                for line in table
                if line.entrant == crowned or line.entrant in played
            ),
            key=lambda line: line.entrant == crowned,
            reverse=True,
        )
        first = 1 if king is not None else 2
    counted = _counted(order, results)
    names = _names(session, list(entrants.values()))
    return [
        StandingRow(
            position=place,
            entrant_id=line.entrant,
            user_id=entrants[line.entrant].user_id,
            team_id=entrants[line.entrant].team_id,
            name=names.get(line.entrant),
            points=line.points,
            game_diff=line.game_diff,
            **counted[line.entrant],
        )
        for place, line in enumerate(table, start=first)
    ]


def _reached(
    session: OrmSession,
    stage: EventStage,
    order: Sequence[int],
    series: Sequence[Series],
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


def _third_place(
    stage: EventStage, numbers: dict[int | None, int], series: Sequence[Series]
) -> Series | None:
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


def _king(
    session: OrmSession, field: Sequence[EventEntrant], series: Sequence[Series]
) -> EventEntrant | None:
    """The entrant who wears the crown of the division this field plays in.

    The crown counts only on a live row of that division, and the player's
    seat in the field stands for the race row he wears it on. A stage that
    runs no divisions has no row to store a crown on, so its throne is the
    winner of the last series it scored.
    """
    division_id = next(
        (row.division_id for row in field if row.division_id is not None), None
    )
    if division_id is None:
        done = [row for row in series if scored(row)]
        winner = entrant_of(done[-1]) if done else None
        return next((row for row in field if ident(row) == winner), None)
    division = session.get(EventDivision, division_id)
    wearer = (
        session.get(EventEntrant, division.king_entrant_id)
        if division is not None and division.king_entrant_id is not None
        else None
    )
    if (
        wearer is None
        or wearer.division_id != division_id
        or wearer.withdrawn_at is not None
    ):
        return None
    return next(
        (
            row
            for row in field
            if row.user_id is not None and row.user_id == wearer.user_id
        ),
        wearer,
    )


def _counted(
    order: Sequence[int], results: Sequence[tuple[int, int | None, int, int]]
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
    teams = {
        ident(team): team.name
        for team in session.scalars(
            select(Team).where(
                col(Team.id).in_({row.team_id for row in field if row.team_id})
            )
        )
    }
    return {
        ident(row): teams.get(row.team_id) if row.team_id else users.get(row.user_id)
        for row in field
    }


def _award(
    session: OrmSession,
    row: Series,
    to_first: bool,
    kind: str,
    wins: int | None = None,
) -> None:
    """Write a result no game was played for, to one side of the series."""
    maps = wins if wins is not None else series_wins(session, row)
    row.player1_score, row.player2_score = (maps, 0) if to_first else (0, maps)
    row.result_kind = kind
    session.flush()
