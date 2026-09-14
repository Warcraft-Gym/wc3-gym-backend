"""The rules one series plays under, with or without a fixture.

A series inside a fixture reads them from the season, as GNL always has. A
series generated into a bracket reads its best-of from its round, its map
rules from its stage, and its map pool from the event either way. The shape
of the series decides, never the kind of the event.

The side a caller acts for hangs on the same round or fixture, so it is
answered here too.
"""

from collections.abc import Iterable
from typing import Literal, NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.map_order import DEFAULT_RULES, rules_of
from app.models.base import ident
from app.models.event_entrant import EventEntrant
from app.models.event_stage import EventStage
from app.models.match import Match
from app.models.relationships import DBEventRound, round_row
from app.models.season import Season
from app.models.series import Series, SeriesPublic, SeriesRulesPublic
from app.models.user_team_season import DBUserTeamSeason

# The games a series holds when neither a season nor a stage names them
DEFAULT_BEST_OF = len(rules_of(None))


class SeriesRules(NamedTuple):
    """One rule per game, the games the best-of holds, and the map ids the
    veto draws from."""

    map_rules: str
    best_of: int
    map_pool: list[int]


def series_round(session: OrmSession, series: Series) -> DBEventRound | None:
    """The round a series is played in: the fixture's playday, else its own."""
    if series.match is not None:
        return round_row(session, series.match.season_id, series.match.playday)
    return session.get(DBEventRound, series.round_id) if series.round_id else None


def series_event(session: OrmSession, series: Series) -> Season | None:
    """The event a series belongs to, through its fixture or through its round."""
    if series.match is not None:
        return series.match.season
    round_ = series_round(session, series)
    return session.get(Season, round_.season_id) if round_ else None


def stands_on_side(series: Series, side: int) -> int | None:
    """Who stands on one side: its entrant, else the player a GNL row names."""
    if side == 1:
        return series.entrant1_id or series.player1_id
    return series.entrant2_id or series.player2_id


def acts_for_side(
    session: OrmSession, series: Series, user_id: int | None
) -> Literal[1, 2] | None:
    """The side the caller acts for: the player of that side, or a member of
    the roster the side's team fields for the event.

    The entrant row names the event itself, which is the event of the series'
    round or fixture, so the roster is read against that id.
    """
    if user_id is None:
        return None
    if series.player1_id == user_id:
        return 1
    if series.player2_id == user_id:
        return 2
    sides: dict[int, Literal[1, 2]] = {
        side_id: side
        for side_id, side in ((series.entrant1_id, 1), (series.entrant2_id, 2))
        if side_id is not None
    }
    if not sides:
        return None
    for entrant in session.scalars(
        select(EventEntrant).where(col(EventEntrant.id).in_(sides))
    ):
        key = (user_id, entrant.team_id, entrant.event_id)
        if entrant.team_id and session.get(DBUserTeamSeason, key) is not None:
            return sides[ident(entrant)]
    return None


def series_rules(session: OrmSession, series: Series) -> SeriesRules:
    """The map rules, the best-of and the map pool of one series."""
    event = series_event(session, series)
    pool = [link.map_id for link in event.maps] if event else []
    if series.match is not None:
        rules = event.map_rules if event else None
        return SeriesRules(rules or DEFAULT_RULES, len(rules_of(rules)), pool)
    round_ = series_round(session, series)
    stage = (
        session.get(EventStage, round_.stage_id) if round_ and round_.stage_id else None
    )
    best_of = (round_.best_of if round_ else None) or (stage.best_of if stage else None)
    rules = stage.map_rules if stage else None
    return SeriesRules(rules or DEFAULT_RULES, best_of or DEFAULT_BEST_OF, pool)


def fill_rules(
    session: OrmSession, rows: Iterable[SeriesPublic | None]
) -> dict[int, int]:
    """Fill the rules of every series and answer the event of the ones that
    hold no fixture, which the race fill then keys on.

    A fixture already carries its season, so only the loose series cost a
    statement, and one statement covers all of them.
    """
    loose: list[SeriesPublic] = []
    for row in rows:
        if row is None:
            continue
        season = row.match.season if row.match else None
        if season is None:
            loose.append(row)
            continue
        row.rules = SeriesRulesPublic(
            map_rules=season.map_rules or DEFAULT_RULES,
            best_of=len(rules_of(season.map_rules)),
        )
    if not loose:
        return {}
    found = _resolve(session, {row.id for row in loose})
    events: dict[int, int] = {}
    for row in loose:
        resolved = found.get(row.id)
        if resolved is None:
            continue
        event_id, map_rules, best_of = resolved
        row.rules = SeriesRulesPublic(map_rules=map_rules, best_of=best_of)
        if event_id is not None:
            events[row.id] = event_id
    return events


def _resolve(
    session: OrmSession, series_ids: set[int]
) -> dict[int, tuple[int | None, str, int]]:
    """The event, the map rules and the best-of of every named series, in one
    statement: through its fixture's season, else through its round and stage."""
    if not series_ids:
        return {}
    event_id = func.coalesce(col(Match.season_id), col(DBEventRound.season_id))
    rows = session.execute(
        select(
            col(Series.id),
            col(Series.match_id),
            event_id,
            col(Season.map_rules),
            col(DBEventRound.best_of),
            col(EventStage.map_rules),
            col(EventStage.best_of),
        )
        .select_from(Series)
        .outerjoin(Match, col(Match.id) == col(Series.match_id))
        .outerjoin(DBEventRound, col(DBEventRound.id) == col(Series.round_id))
        .outerjoin(EventStage, col(EventStage.id) == col(DBEventRound.stage_id))
        .outerjoin(Season, col(Season.id) == event_id)
        .where(col(Series.id).in_(series_ids))
    ).all()
    found: dict[int, tuple[int | None, str, int]] = {}
    for (
        row_id,
        match_id,
        event,
        season_rules,
        round_best,
        stage_rules,
        stage_best,
    ) in rows:
        if match_id is not None:
            found[row_id] = (
                event,
                season_rules or DEFAULT_RULES,
                len(rules_of(season_rules)),
            )
        else:
            found[row_id] = (
                event,
                stage_rules or DEFAULT_RULES,
                round_best or stage_best or DEFAULT_BEST_OF,
            )
    return found
