"""What a cup series reads beside its own row: its rules, races, MMR and sides.

The rules come from the round and the stage the series is drawn in: the
best-of of the round, else of the stage, and the map rules the cup vetoes
by. The race of a side is the off race it reported, else the race its
entrant entered on. The MMR is the current one while the cup runs, and the
one of its day once it is finished.

Who acts for a side is answered here as well: the player a 1v1 side names,
or any member of the cup team a team side fields. Every cup write asks it.
A cup team checks in only once its roster is full, on every check-in route.
"""

from collections.abc import Sequence
from typing import Literal, NamedTuple

from sqlalchemy import Integer, String, cast, column, func, select, values
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.sql.selectable import FromClause
from sqlmodel import col

from app.core.best_of import largest_best_of
from app.core.brackets import head_start
from app.core.exceptions import BadRequestError
from app.core.map_order import cup_rules, default_rules, rules_of
from app.models.base import ident
from app.models.cup_series import CupSeries, CupSeriesPublic
from app.models.cup_settings import CupSettings
from app.models.cup_team import CupTeamMember
from app.models.event_entrant import EventEntrant
from app.models.event_stage import EventStage
from app.models.relationships import DBEventRound, DBMapSeason
from app.models.season import Season
from app.models.series import SeriesRulesPublic
from app.models.w3c_ladder_match import W3CLadderMatch
from app.services import ladder
from app.services.series_rules import map_pool

# The games a series holds when neither the round nor the stage names them
DEFAULT_BEST_OF = len(rules_of(None))


class CupRules(NamedTuple):
    """One rule per game, the games the best-of holds, and the map ids the
    veto draws from."""

    map_rules: str
    best_of: int
    map_pool: list[int]


# A check-in of a cup team whose invited players have not all accepted
SHORT_TEAM = "The team checks in once every player has accepted their invitation"


def team_players(session: OrmSession, team_ids: Sequence[int]) -> dict[int, int]:
    """How many players each cup team holds, its captain included, in one read."""
    if not team_ids:
        return {}
    return {
        team_id: total
        for team_id, total in session.execute(
            select(col(CupTeamMember.team_id), func.count())
            .where(col(CupTeamMember.team_id).in_(team_ids))
            .group_by(col(CupTeamMember.team_id))
        ).all()
    }


def team_short(session: OrmSession, event: Season, entrant: EventEntrant) -> bool:
    """Whether the entrant is a cup team with fewer players than the cup's team size."""
    team_id = entrant.cup_team_id
    if team_id is None or not event.team_size:
        return False
    return team_players(session, [team_id]).get(team_id, 0) < event.team_size


def hold_complete_team(
    session: OrmSession, event: Season, entrant: EventEntrant
) -> None:
    """Refuse the check-in of a cup team that still waits for a player."""
    if team_short(session, event, entrant):
        raise BadRequestError(SHORT_TEAM)


def event_of(session: OrmSession, row: CupSeries) -> Season:
    """The cup a series is played in, through its round."""
    round_ = session.get_one(DBEventRound, row.round_id)
    return session.get_one(Season, round_.season_id)


def rules_of(session: OrmSession, row: CupSeries) -> CupRules:
    """The map rules, the best-of and the map pool of one cup series."""
    round_ = session.get_one(DBEventRound, row.round_id)
    event = session.get_one(Season, round_.season_id)
    stage = session.get(EventStage, round_.stage_id) if round_.stage_id else None
    pool = [link.map_id for link in map_pool(session, event)]
    best_of = round_.best_of or (stage.best_of if stage else None) or DEFAULT_BEST_OF
    from app.services.cup_divisions import custom_game

    if custom_game(session, event):
        # a custom game cup plays every game on its one map: a fixed map each game
        return CupRules(",".join(["fixed"] * best_of), best_of, pool)
    if event.veto_by_best_of:
        return CupRules(cup_rules(best_of), best_of, pool)
    stage_rules = stage.map_rules if stage else None
    return CupRules(stage_rules or default_rules(best_of), best_of, pool)


def hold_pool(session: OrmSession, event: Season) -> None:
    """Refuse a cup that vetoes by best-of while its pool is smaller than its
    longest series: every game needs a map of its own."""
    if not event.veto_by_best_of:
        return
    stages = session.scalars(
        select(EventStage).where(col(EventStage.event_id) == ident(event))
    ).all()
    need = max(
        (largest_best_of(stage.best_of, stage.best_of_by_round) for stage in stages),
        default=0,
    )
    have = session.scalar(
        select(func.count())
        .select_from(DBMapSeason)
        .where(col(DBMapSeason.season_id) == ident(event))
    )
    if need > (have or 0):
        raise BadRequestError(
            f"A Bo{need} needs {need} {'map' if need == 1 else 'maps'} in the pool; "
            f"the pool holds {have or 0}"
        )


def acts_for_side(
    session: OrmSession, row: CupSeries, user_id: int | None
) -> Literal[1, 2] | None:
    """The side the caller plays for: the player a side names, or a member of
    the cup team a side fields. A runner acts for either side; the routes
    answer that before they ask here, so a null user is nobody."""
    if user_id is None:
        return None
    if row.player1_id == user_id:
        return 1
    if row.player2_id == user_id:
        return 2
    sides: dict[int, Literal[1, 2]] = {
        entrant_id: side
        for entrant_id, side in ((row.entrant1_id, 1), (row.entrant2_id, 2))
        if entrant_id is not None
    }
    if not sides:
        return None
    found = session.execute(
        select(col(EventEntrant.id))
        .join(
            CupTeamMember, col(CupTeamMember.team_id) == col(EventEntrant.cup_team_id)
        )
        .where(col(EventEntrant.id).in_(sides), col(CupTeamMember.user_id) == user_id)
    ).first()
    return sides[found[0]] if found else None


def fill(
    session: OrmSession, rows: Sequence[CupSeries], publics: Sequence[CupSeriesPublic]
) -> None:
    """Fill the rules, the head start, the race and the MMR of both sides of
    every series.

    The rows carry their entrants, so the races cost nothing; the rules and
    the head start are one statement and the MMR two, three while the cup's
    day is over.
    """
    if not rows:
        return
    by_id = {ident(row): row for row in rows}
    found = session.execute(
        select(
            col(CupSeries.id),
            col(Season.id),
            col(Season.veto_by_best_of),
            col(DBEventRound.best_of),
            col(EventStage.map_rules),
            col(EventStage.best_of),
            col(CupSettings.custom_game),
            col(DBEventRound.name),
            col(EventStage.grand_final_modifier),
            col(EventStage.grand_final_lead),
        )
        .join(DBEventRound, col(DBEventRound.id) == col(CupSeries.round_id))
        .join(Season, col(Season.id) == col(DBEventRound.season_id))
        .outerjoin(EventStage, col(EventStage.id) == col(DBEventRound.stage_id))
        .outerjoin(CupSettings, col(CupSettings.event_id) == col(Season.id))
        .where(col(CupSeries.id).in_(by_id))
    ).all()
    events: dict[int, int] = {}
    for (
        series_id,
        event_id,
        by_best_of,
        round_best,
        stage_rules,
        stage_best,
        custom,
        round_name,
        modifier,
        lead,
    ) in found:
        best_of = round_best or stage_best or DEFAULT_BEST_OF
        map_rules = (
            # a custom game cup plays every game on its one map
            ",".join(["fixed"] * best_of)
            if custom
            else cup_rules(best_of)
            if by_best_of
            else stage_rules or default_rules(best_of)
        )
        events[series_id] = event_id
        for public in publics:
            if public.id == series_id:
                public.rules = SeriesRulesPublic(map_rules=map_rules, best_of=best_of)
                public.head_start = head_start(round_name, modifier, lead)
    for public in publics:
        row = by_id.get(public.id)
        if row is None:
            continue
        entered1 = row.entrant1.race if row.entrant1 and row.entrant1.race else None
        entered2 = row.entrant2.race if row.entrant2 and row.entrant2.race else None
        public.player1_race = public.player1_off_race or (
            entered1.value if entered1 else None
        )
        public.player2_race = public.player2_off_race or (
            entered2.value if entered2 else None
        )
    _fill_mmrs(session, publics, events)


def _fill_mmrs(
    session: OrmSession, publics: Sequence[CupSeriesPublic], events: dict[int, int]
) -> None:
    """Rate both sides of every series on the race the row names: the current
    rating while the cup runs, the rating of its day once it is finished."""
    # app.services.events imports this module, so its rules come in on the call
    from app.services.events import race_ratings

    event_ids = set(events.values())
    if not event_ids:
        return
    running = set(
        session.scalars(
            select(col(Season.id)).where(col(Season.id).in_(event_ids), Season.running)
        )
    )
    finished = [row for row in publics if events.get(row.id) not in running]
    by_event: dict[int, list[CupSeriesPublic]] = {}
    for row in finished:
        if row.id in events:
            by_event.setdefault(events[row.id], []).append(row)
    for event_id, played in by_event.items():
        _mmrs_of_the_day(session, event_id, played)
    current = [row for row in publics if events.get(row.id) in running]
    rated = race_ratings(
        session,
        [
            (player_id, race)
            for row in current
            for player_id, race in (
                (row.player1_id, row.player1_race),
                (row.player2_id, row.player2_race),
            )
        ],
    )
    for row in current:
        if row.player1_id and row.player1_race:
            row.player1_mmr = rated.get((row.player1_id, row.player1_race))
        if row.player2_id and row.player2_race:
            row.player2_mmr = rated.get((row.player2_id, row.player2_race))


def _mmrs_of_the_day(
    session: OrmSession, event_id: int, rows: list[CupSeriesPublic]
) -> None:
    """Both sides of every series of one finished cup on the day of its round,
    else of the cup, in one statement that sends two races per row."""
    sides = (
        values(
            column("id", Integer),
            column("race1", String),
            column("race2", String),
            name="sides",
        )
        .data([(row.id, row.player1_race, row.player2_race) for row in rows])
        .cte()
    )
    # a bound value reaches Postgres as text, which its race enum does not compare to
    ladder_table: FromClause = getattr(W3CLadderMatch, "__table__")  # noqa: B009
    race1, race2 = (
        cast(race, ladder_table.c.race.type) for race in (sides.c.race1, sides.c.race2)
    )
    seasons = select(ladder.w3c_seasons(session, [event_id]).c.wc3_season)
    instant = ladder.midnight_utc(
        session, func.coalesce(col(DBEventRound.start_date), col(Season.start_date))
    )
    rated = {
        series_id: (mmr1, mmr2)
        for series_id, mmr1, mmr2 in session.execute(
            select(
                sides.c.id,
                ladder.mmr_at(col(CupSeries.player1_id), race1, instant, seasons),
                ladder.mmr_at(col(CupSeries.player2_id), race2, instant, seasons),
            )
            .join(CupSeries, col(CupSeries.id) == sides.c.id)
            .join(DBEventRound, col(DBEventRound.id) == col(CupSeries.round_id))
            .join(Season, col(Season.id) == col(DBEventRound.season_id))
        )
    }
    for row in rows:
        row.player1_mmr, row.player2_mmr = rated.get(row.id, (None, None))
