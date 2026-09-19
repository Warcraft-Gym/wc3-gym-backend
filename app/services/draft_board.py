"""Everything the draft board of one match shows, in one read, and the
meetings of one pair on demand.

The board answers figures, never rows. A fixed number of statements fills it
whatever the size of the two rosters: the ratings, the games, the record
against each race, the recent form, the blocks and the head to head are each
one grouped read over every player at once, and the shared hours of every
pair are worked out in memory from blocks that were read once per player.

A pair carries only what a browser cannot compute. The MMR difference is
absent: the browser subtracts the two ratings the player list already holds.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from itertools import product
from typing import Any

from sqlalchemy import Row, and_, case, func, or_, select
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import aliased
from sqlmodel import col

from app.core import free_time
from app.core.db import Session
from app.core.exceptions import NotFoundError
from app.core.fantasy import race_value
from app.models.base import ident
from app.models.draft_board import (
    DraftBoard,
    DraftBoardPair,
    DraftBoardPlayer,
    PairMeeting,
)
from app.models.draft_series import DraftSeries
from app.models.enums import StageFormat
from app.models.event_stage import MAX_MMR_DIFFERENCE, EventStage
from app.models.match import Match
from app.models.relationships import (
    DBEventRound,
    DBUserSeasonSignup,
    round_row,
)
from app.models.season import LEAGUE_SHORT_NAME, Season
from app.models.series import Series
from app.models.user import User
from app.models.user_block import UserBlock, UserBusy
from app.models.user_team_season import DBUserTeamSeason
from app.models.w3c_ladder_match import W3CLadderMatch
from app.services import derived, events, ladder, soft_blocks

# How many meetings the pair read answers, newest first
MEETINGS_LIMIT = 20


def board(match_id: int) -> DraftBoard:
    """Every figure the draft board of one match draws."""
    with Session.begin() as session:
        match = session.get(Match, match_id)
        if match is None:
            raise NotFoundError("match_not_found")
        event = session.get(Season, match.season_id)
        if event is None:
            raise NotFoundError("season_not_found")
        event_id = ident(event)
        roster = _roster(session, event_id, (match.team1_id, match.team2_id))
        user_ids = [row.user_id for row in roster]
        sides = [(row.user_id, race_value(row.race)) for row in roster]

        ratings = events.race_ratings(session, sides)
        games = events.race_games(session, sides, event.min_games_seasons)
        vs_race = ladder.season_vs_race(session, user_ids, event)
        form = ladder.recent_form(session, user_ids, event_id)

        window = soft_blocks.round_window(
            round_row(session, event_id, match.playday), event
        )
        spans = _blocked(session, user_ids, window)

        team1 = [row for row in roster if row.team_id == match.team1_id]
        team2 = [row for row in roster if row.team_id == match.team2_id]
        met = _head_to_head(
            session, [row.user_id for row in team1], [row.user_id for row in team2]
        )
        return DraftBoard(
            match_id=match_id,
            event_id=event_id,
            playday=match.playday,
            team1_id=match.team1_id,
            team2_id=match.team2_id,
            max_mmr_difference=_max_mmr_difference(session, event_id),
            series_per_round=event.series_per_round,
            published_series=_count(session, col(Series.match_id), match_id),
            open_drafts=_count(session, col(DraftSeries.match_id), match_id),
            players=[
                _player(row, event, ratings, games, vs_race, form) for row in roster
            ],
            pairs=[
                _pair(one.user_id, two.user_id, window, spans, met)
                for one, two in product(team1, team2)
            ],
        )


def meetings(user_a: int, user_b: int) -> list[PairMeeting]:
    """Every finished series the two players played, newest first, capped at
    `MEETINGS_LIMIT`, with the MMR each held at the time.

    One statement: the meetings carry the race each side played, and the two
    ratings hang off them as ranked reads of the ladder rows before the
    series, so the answer costs the same whoever the pair is.
    """
    if user_a == user_b:
        return []
    with Session.begin() as session:
        return [
            PairMeeting(
                series_id=row.series_id,
                date_time=row.date_time,
                event_label=_label(row.league_short_name, row.event_name),
                player1_score=int(row.score_a or 0),
                player2_score=int(row.score_b or 0),
                player1_race=race_value(row.race_a),
                player2_race=race_value(row.race_b),
                player1_mmr=row.mmr_a,
                player2_mmr=row.mmr_b,
            )
            for row in _meeting_rows(session, user_a, user_b)
        ]


def _roster(
    session: OrmSession, event_id: int, team_ids: tuple[int, int]
) -> Sequence[Row[Any]]:
    """Both rosters of the match with the race each player registered on."""
    return session.execute(
        select(
            col(DBUserTeamSeason.user_id).label("user_id"),
            col(DBUserTeamSeason.team_id).label("team_id"),
            col(DBUserSeasonSignup.race).label("race"),
        )
        .outerjoin(
            DBUserSeasonSignup,
            and_(
                col(DBUserSeasonSignup.user_id) == col(DBUserTeamSeason.user_id),
                col(DBUserSeasonSignup.season_id) == event_id,
            ),
        )
        .where(
            col(DBUserTeamSeason.season_id) == event_id,
            col(DBUserTeamSeason.team_id).in_(team_ids),
        )
        .order_by(col(DBUserTeamSeason.team_id), col(DBUserTeamSeason.user_id))
    ).all()


def _player(
    row: Row[Any],
    event: Season,
    ratings: dict[tuple[int, str], int],
    games: dict[tuple[int, str], int],
    vs_race: dict[int, dict[str, list[int]]],
    form: dict[int, str],
) -> DraftBoardPlayer:
    """One roster row with its rating, its games and its ladder figures."""
    race = race_value(row.race)
    key = (row.user_id, race) if race else None
    counted = games.get(key, 0) if key else 0
    return DraftBoardPlayer(
        user_id=row.user_id,
        team_id=row.team_id,
        race=race,
        mmr=ratings.get(key) if key else None,
        games=counted,
        games_warning=_games_warning(event, key in games if key else False, counted),
        vs_race=vs_race.get(row.user_id, {}),
        form=form.get(row.user_id, ""),
    )


def _games_warning(event: Season, has_stats: bool, games: int) -> str | None:
    """The games-rule flag: no stored W3C row at all, else too few games.

    An event that names no `min_games` sets no rule, so nothing is flagged.
    """
    if event.min_games is None:
        return None
    if not has_stats:
        return "no_w3c_stats"
    return "under_min_games" if games < event.min_games else None


def _pair(
    player1_id: int,
    player2_id: int,
    window: tuple[datetime, datetime],
    spans: dict[int, list[free_time.Interval]],
    met: dict[tuple[int, int], Row[Any]],
) -> DraftBoardPair:
    """One pairing: its shared hours, and its score when the two have met."""
    start, end = window
    shared = free_time.free(start, end, spans[player1_id], spans[player2_id])
    row = met.get((player1_id, player2_id))
    return DraftBoardPair(
        player1_id=player1_id,
        player2_id=player2_id,
        hours=soft_blocks.free_hours(shared),
        wins=int(row.wins or 0) if row is not None else None,
        losses=int(row.losses or 0) if row is not None else None,
        last_event=row.event_name if row is not None else None,
    )


def _blocked(
    session: OrmSession, user_ids: Sequence[int], window: tuple[datetime, datetime]
) -> dict[int, list[free_time.Interval]]:
    """What every player blocked inside the window, in three statements.

    The zones, the repeating blocks and the busy days are read for the whole
    roster at once and merged in memory, so a board of sixty-four pairings
    reads the blocks of sixteen players, not of sixty-four.
    """
    start, end = window
    zones: dict[int, str | None] = {
        user_id: zone
        for user_id, zone in session.execute(
            select(col(User.id), col(User.timezone)).where(col(User.id).in_(user_ids))
        )
    }
    blocks: dict[int, list[UserBlock]] = {user_id: [] for user_id in user_ids}
    for row in session.scalars(
        select(UserBlock).where(col(UserBlock.user_id).in_(user_ids))
    ):
        blocks[row.user_id].append(row)
    busy: dict[int, list[UserBusy]] = {user_id: [] for user_id in user_ids}
    for row in session.scalars(
        select(UserBusy).where(
            col(UserBusy.user_id).in_(user_ids),
            # a local last day can sit a calendar day behind the window start
            col(UserBusy.last_day) >= start.date() - timedelta(days=1),
        )
    ):
        busy[row.user_id].append(row)
    return {
        user_id: free_time.blocked(
            zones.get(user_id), blocks[user_id], busy[user_id], start, end
        )
        for user_id in user_ids
    }


def _head_to_head(
    session: OrmSession, team1_ids: Sequence[int], team2_ids: Sequence[int]
) -> dict[tuple[int, int], Row[Any]]:
    """The score of every pairing that has met, over every finished series on
    the app, keyed in (team1 player, team2 player) order.

    One grouped statement for both rosters: a pair costs no statement of its
    own, and a pair that never met is absent. The last meeting is the newest
    event the two played in, which is the highest event id.
    """
    if not team1_ids or not team2_ids:
        return {}
    first = col(Series.player1_id).in_(team1_ids)
    own = case((first, col(Series.player1_score)), else_=col(Series.player2_score))
    opp = case((first, col(Series.player2_score)), else_=col(Series.player1_score))
    mine = case((first, col(Series.player1_id)), else_=col(Series.player2_id))
    theirs = case((first, col(Series.player2_id)), else_=col(Series.player1_id))
    event_id = func.coalesce(col(Match.season_id), col(DBEventRound.season_id))
    grouped = (
        select(
            mine.label("user_a"),
            theirs.label("user_b"),
            func.sum(case((own > opp, 1), else_=0)).label("wins"),
            func.sum(case((opp > own, 1), else_=0)).label("losses"),
            func.max(event_id).label("last_event_id"),
        )
        .join(Match, col(Match.id) == Series.match_id, isouter=True)
        .join(DBEventRound, col(DBEventRound.id) == Series.round_id, isouter=True)
        .where(
            or_(
                and_(first, col(Series.player2_id).in_(team2_ids)),
                and_(
                    col(Series.player1_id).in_(team2_ids),
                    col(Series.player2_id).in_(team1_ids),
                ),
            ),
            # an unplayed series carries no map score and pays no record
            func.coalesce(col(Series.player1_score), 0)
            + func.coalesce(col(Series.player2_score), 0)
            > 0,
        )
        .group_by(mine, theirs)
        .subquery()
    )
    rows = session.execute(
        select(
            grouped.c.user_a,
            grouped.c.user_b,
            grouped.c.wins,
            grouped.c.losses,
            col(Season.name).label("event_name"),
        ).join(Season, col(Season.id) == grouped.c.last_event_id, isouter=True)
    ).all()
    return {(row.user_a, row.user_b): row for row in rows}


def _max_mmr_difference(session: OrmSession, event_id: int) -> int | None:
    """The captain-draft stage's largest MMR difference, reading a null row as
    the default the stage payload reads it as. No such stage answers none."""
    row = session.execute(
        select(col(EventStage.max_mmr_difference)).where(
            col(EventStage.event_id) == event_id,
            col(EventStage.format) == StageFormat.gnl,
        )
    ).first()
    if row is None:
        return None
    return row[0] if row[0] is not None else MAX_MMR_DIFFERENCE


def _count(session: OrmSession, match_column: Any, match_id: int) -> int:  # noqa: ANN401
    """How many rows of that table the match holds."""
    return session.scalar(select(func.count()).where(match_column == match_id)) or 0


def _label(short_name: str | None, event_name: str | None) -> str | None:
    """The label of an event: "{league} - {event}", the event name where it has no league."""
    if not event_name:
        return None
    return f"{short_name} - {event_name}" if short_name else event_name


def _meeting_rows(session: OrmSession, user_a: int, user_b: int) -> Sequence[Row[Any]]:
    """The finished series between the two, newest first, with the race each
    played and the MMR each held going into it.

    One statement. The two ratings are ranked reads of the ladder rows that
    close before the series, so neither the ladder rows nor an extra round
    trip per meeting reach the caller. A series with no time is dated by the
    first day of its round.
    """
    signup_a, signup_b = aliased(DBUserSeasonSignup), aliased(DBUserSeasonSignup)
    first = col(Series.player1_id) == user_a
    # the series' own time, else the first day of its round; it orders the list
    # and dates the ladder read, and it never leaves the statement, because a
    # date read back through a timestamp type is not a timestamp
    instant = func.coalesce(col(Series.date_time), col(DBEventRound.start_date))
    met = (
        select(
            col(Series.id).label("series_id"),
            col(Series.date_time).label("date_time"),
            instant.label("instant"),
            case(
                (first, col(Series.player1_score)), else_=col(Series.player2_score)
            ).label("score_a"),
            case(
                (first, col(Series.player2_score)), else_=col(Series.player1_score)
            ).label("score_b"),
            case(
                (
                    first,
                    derived.race_of(col(Series.player1_off_race), signup_a),
                ),
                else_=derived.race_of(col(Series.player2_off_race), signup_a),
            ).label("race_a"),
            case(
                (
                    first,
                    derived.race_of(col(Series.player2_off_race), signup_b),
                ),
                else_=derived.race_of(col(Series.player1_off_race), signup_b),
            ).label("race_b"),
            func.coalesce(col(Match.season_id), col(DBEventRound.season_id)).label(
                "event_id"
            ),
        )
        .join(Match, col(Match.id) == Series.match_id, isouter=True)
        .join(DBEventRound, col(DBEventRound.id) == Series.round_id, isouter=True)
        .join(signup_a, _signed_up(signup_a, user_a), isouter=True)
        .join(signup_b, _signed_up(signup_b, user_b), isouter=True)
        .where(
            or_(
                and_(first, col(Series.player2_id) == user_b),
                and_(
                    col(Series.player1_id) == user_b,
                    col(Series.player2_id) == user_a,
                ),
            ),
            func.coalesce(col(Series.player1_score), 0)
            + func.coalesce(col(Series.player2_score), 0)
            > 0,
        )
        .subquery()
    )
    return session.execute(
        select(
            met.c.series_id,
            met.c.date_time,
            met.c.score_a,
            met.c.score_b,
            met.c.race_a,
            met.c.race_b,
            col(Season.name).label("event_name"),
            LEAGUE_SHORT_NAME,
            _mmr_at(user_a, met.c.race_a, met.c.instant).label("mmr_a"),
            _mmr_at(user_b, met.c.race_b, met.c.instant).label("mmr_b"),
        )
        .join(Season, col(Season.id) == met.c.event_id, isouter=True)
        .order_by(met.c.instant.desc(), met.c.series_id.desc())
        .limit(MEETINGS_LIMIT)
    ).all()


def _signed_up(signup: Any, user_id: int) -> Any:  # noqa: ANN401
    """The signup join of one named player: his row for the series' event."""
    return and_(
        col(signup.user_id) == user_id,
        col(signup.season_id) == col(Match.season_id),
    )


def _mmr_at(user_id: int, race: Any, instant: Any) -> Any:  # noqa: ANN401
    """The MMR the player took into a series: `mmr_after` of his last rated
    ladder game on the race he played, before the series started.

    A ranked read that hangs off the meeting row, so the whole list costs no
    statement of its own and no ladder row is sent.
    """
    game = aliased(W3CLadderMatch)
    return (
        select(col(game.mmr_after))
        .where(
            col(game.user_id) == user_id,
            col(game.race) == race,
            col(game.start_time) < instant,
            col(game.mmr_after).is_not(None),
        )
        .order_by(col(game.start_time).desc(), col(game.id).desc())
        .limit(1)
        .scalar_subquery()
    )
