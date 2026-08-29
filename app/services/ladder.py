"""Store the w3champions ladder matches of the GNL players.

The ladder page aggregates these rows at read time, so the sync only has to
put every match of every player on a team in the table once.
"""

import logging
from collections import defaultdict
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import (
    ColumnElement,
    Row,
    and_,
    case,
    distinct,
    extract,
    func,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import aliased
from sqlmodel import col

from app.core import achievements, ladder
from app.core.db import Session
from app.core.exceptions import (
    BadRequestError,
    ExternalServiceError,
    NotFoundError,
    W3CThrottledError,
)
from app.models.base import ident
from app.models.enums import Race
from app.models.ladder_achievement import LadderAchievement
from app.models.ladder_sync import LadderSync
from app.models.relationships import DBTeamSeasonCoach, DBUserSeasonSignup
from app.models.season import Season
from app.models.team import Team
from app.models.types import utcnow
from app.models.user import User, UserReduced
from app.models.user_team_season import DBUserTeamSeason
from app.models.w3c_ladder_match import (
    LadderDay,
    LadderMatchPublic,
    LadderMmr,
    LadderPlayer,
    LadderSeason,
    LadderSeasonDay,
    LadderSyncResult,
    LadderTeam,
    SeasonLadder,
    UserLadder,
    W3CLadderMatch,
    W3CLadderMatchCreate,
)
from app.models.w3c_stats import W3CSyncFailure, W3CSyncResult
from app.services.users import SYNC_MAX_AGE, W3C_SYNC_WORKERS, UserService
from app.services.w3c import THROTTLED_MESSAGE, W3CService

if TYPE_CHECKING:
    from app.services.settings import SettingsService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Plan:
    """What one sync run asks w3champions for.

    `seasons` names the w3champions seasons to read; without one the walk
    starts at `walk_from` and discovers them.
    """

    since: datetime
    open_season: int
    seasons: tuple[int, ...] | None
    walk_from: int


class LadderService:
    """Ladder matches are written by the sync alone, so this service has no
    CRUD. The reads aggregate them in SQL and store nothing."""

    def __init__(self, settings_app_service: "SettingsService | None" = None) -> None:
        self.settings_app_service = settings_app_service
        self.user_app_service = UserService(settings_app_service=settings_app_service)

    def season_ladder(self, season_id: int) -> SeasonLadder:
        """The ladder of one season: its teams, its players and its hours.

        Thirteen statements, whatever the number of players: the season, the
        signups with their team, the achievement set this season pays, the
        w3champions seasons the window sits in, the sync stamps of the roster,
        one group each for the totals, the MMR spans, the player days, the
        races, the hours and the season days, then the matches the
        achievements read and the season's coaches.
        """
        with Session.begin() as session:
            season = session.get(Season, season_id)
            if season is None:
                raise NotFoundError("Season not found")

            roster = _roster(session, season_id)

            user_ids = [row.user_id for row in roster]
            window = _window(season)
            stamps = _stamps(session, user_ids, _w3c_seasons_for(session, season))
            scope = _scope(user_ids, window, season_id)
            totals = _totals(session, scope)
            spans = _mmr_span(session, _mmr_scope(user_ids, window, season_id))
            days = _per_day(session, scope)
            races = _vs_race(session, scope)
            by_hour = _by_hour(session, scope)
            games = _games_per_day(session, scope)
            paid = _paid(session, season_id)
            earned = _earned(session, scope, roster, totals, season_id, paid)
            return SeasonLadder(
                season=LadderSeason(
                    id=ident(season),
                    start_date=season.start_date,
                    end_date=season.end_date,
                    synced_at=_season_stamp(stamps, user_ids),
                ),
                # A match starts on one day, so the days add up to the total
                total_games=sum(games.values()),
                by_hour=by_hour,
                per_day=_season_days(season, games),
                achievement_rules=_rules(paid),
                teams=_teams(roster, totals, spans, days, races, earned, stamps),
            )

    def user_ladder(
        self,
        user_id: int,
        season_id: int | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> UserLadder:
        """One player's record, and one page of the matches behind it.

        A season names the window; without one the answer is his whole
        history. Nine statements, thirteen with a season, which adds the
        season, the w3champions seasons its window sits in, its roster and its
        coaches for the achievements that read a team.
        """
        with Session.begin() as session:
            user = session.execute(
                select(
                    col(User.id).label("user_id"),
                    col(User.name).label("name"),
                    col(User.battleTag).label("battleTag"),
                    col(User.country).label("country"),
                    col(User.race).label("race"),
                ).where(col(User.id) == user_id)
            ).first()
            if user is None:
                raise NotFoundError("User not found")

            window = None
            wc3_seasons = None
            if season_id is not None:
                season = session.get(Season, season_id)
                if season is None:
                    raise NotFoundError("Season not found")
                window = _window(season)
                wc3_seasons = _w3c_seasons_for(session, season)

            stamps = _stamps(session, [user_id], wc3_seasons)
            scope = _scope([user_id], window, season_id)
            totals = _totals(session, scope)
            spans = _mmr_span(session, _mmr_scope([user_id], window, season_id))
            roster = _roster(session, season_id) if season_id is not None else []
            paid = _paid(session, season_id)
            earned = _earned(session, scope, roster, totals, season_id, paid)
            answer = _player(
                UserLadder,
                user,
                totals.get(user_id),
                spans.get(user_id),
                _per_day(session, scope).get(user_id, []),
                _vs_race(session, scope).get(user_id, {}),
                earned.get(user_id, []),
                stamps.get(user_id),
            )
            answer.matches = _matches(session, scope, limit, offset)
            return answer

    def sync_season(
        self,
        season_id: int,
        offset: int = 0,
        limit: int = W3C_SYNC_WORKERS,
        max_age: timedelta = SYNC_MAX_AGE,
    ) -> LadderSyncResult:
        """Sync one chunk of the players on a team of the season."""
        with Session.begin() as session:
            if session.get(Season, season_id) is None:
                raise NotFoundError("Season not found")
            # The ladder page counts the players on a team, so the sync walks
            # the same list
            roster = [r for r in _roster(session, season_id) if r.team_id is not None]
        total = len(roster)
        rows = roster[offset : offset + limit]
        users = [
            UserReduced(id=row.user_id, name=row.name, battleTag=row.battleTag)
            for row in rows
        ]

        result = self.sync_season_users(season_id, users, max_age)
        done = offset + len(rows)
        next_offset = done if done < total else None
        return LadderSyncResult(
            **result.model_dump(), total=total, next_offset=next_offset
        )

    def sync_season_users(
        self, season_id: int, users: Sequence[UserReduced], max_age: timedelta
    ) -> W3CSyncResult:
        """Sync these players against the window of one season.

        The window starts at the season start date, so a run backfills as
        well as it refreshes. A player synced more recently than max_age is
        skipped untouched; a max_age of zero syncs everyone.
        """
        with Session.begin() as session:
            season = session.get(Season, season_id)
            if season is None:
                raise NotFoundError("Season not found")
            # A season without dates reads every match the walk reaches
            since, end = _window(season)
            open_window = end >= utcnow()
            seasons = _w3c_seasons_for(session, season)
            # The bootstrap start: a closed window is dated by the matches
            # already stored, an open one ends in the pinned season
            walk_from = None if open_window else _walk_start(session, end)
            fresh_since = utcnow() - max_age
            synced_at = {
                user_id: stamp
                for user_id, stamp in session.execute(
                    select(col(User.id), col(User.ladder_synced_at)).where(
                        col(User.id).in_([user.id for user in users])
                    )
                )
            }

        pending: list[UserReduced] = []
        skipped: list[int] = []
        for user in users:
            stamp = synced_at.get(user.id)
            if stamp is not None and stamp > fresh_since:
                skipped.append(user.id)
            else:
                pending.append(user)

        if pending and seasons and open_window:
            # w3champions can have opened a season no stored match names yet
            open_season = W3CService(
                settings_app_service=self.settings_app_service
            ).current_season()
            seasons = sorted({*seasons, open_season}, reverse=True)

        result = self.sync_users(pending, since, seasons, walk_from)
        result.skipped = skipped
        return result

    def sync_user(self, user_id: int) -> None:
        """Sync one player now: his stats, and his matches of the season
        running today. Outside a season his stats are all there is to read."""
        with Session.begin() as session:
            row = session.get(User, user_id)
            if row is None:
                raise NotFoundError("User not found")
            user = UserReduced.from_user_reduced(row)
            today = utcnow().date()
            season_id = session.scalar(
                select(col(Season.id)).where(
                    Season.start_date <= today, Season.end_date >= today
                )
            )

        if season_id is None:
            self.user_app_service.update_w3c_stats(user)
            return
        result = self.sync_season_users(season_id, [user], timedelta(0))
        if result.failed:
            raise ExternalServiceError(result.failed[0].reason)

    def sync_users(
        self,
        users: Sequence[UserReduced],
        since: datetime,
        seasons: Sequence[int] | None = None,
        walk_from: int | None = None,
    ) -> W3CSyncResult:
        """Sync these players: their stats, and the matches they started at or
        after `since`.

        `seasons` names the w3champions seasons of a GNL window. Naming none,
        which is a window with no stored match to date it, walks down from
        `walk_from` and discovers them.
        """
        result = W3CSyncResult()
        if not users:
            return result

        w3c_service = W3CService(settings_app_service=self.settings_app_service)
        open_season = w3c_service.current_season()
        named = tuple(seasons) if seasons else None
        plan = _Plan(
            since=since,
            open_season=open_season,
            seasons=named,
            walk_from=walk_from or open_season,
        )
        synced: set[int] = set()
        failures: dict[int, str] = {}
        throttled = False

        # Each worker opens its own session; the threads share the engine only
        with ThreadPoolExecutor(W3C_SYNC_WORKERS) as pool:
            futures = {
                pool.submit(self._sync_user, u, w3c_service, plan): u for u in users
            }
            for future in as_completed(futures):
                if future.cancelled():
                    continue
                user = futures[future]
                try:
                    future.result()
                except W3CThrottledError:
                    throttled = True
                    for other in futures:
                        other.cancel()
                except Exception as e:
                    # The reason reaches the client, so it names the class of a
                    # database error and no statement
                    database = isinstance(e, SQLAlchemyError)
                    reason = (
                        f"Database error ({type(e).__name__})" if database else str(e)
                    )
                    failures[user.id] = reason
                    message = (
                        f"Failed to sync ladder matches for user {user.name} "
                        f"(BattleTag: {user.battleTag}): {reason}"
                    )
                    # A database error keeps its traceback in the server log
                    if database:
                        logger.exception(message)
                    else:
                        logger.warning(message)
                else:
                    synced.add(user.id)

        if throttled:
            stopped = [u for u in users if u.id not in synced and u.id not in failures]
            for user in stopped:
                failures[user.id] = THROTTLED_MESSAGE
            logger.warning(
                f"W3Champions throttled the sync, {len(stopped)} player(s) not synced"
            )

        # The report follows the order the caller passed, not the order the
        # workers finished in.
        for user in users:
            if user.id in synced:
                result.synced.append(user.id)
            else:
                result.failed.append(
                    W3CSyncFailure(
                        id=user.id,
                        name=user.name,
                        battleTag=user.battleTag,
                        reason=failures[user.id],
                    )
                )
        return result

    def _sync_user(
        self,
        user: UserReduced,
        w3c_service: W3CService,
        plan: _Plan,
    ) -> None:
        """Sync this player: his w3champions stats, then the matches he still
        owes the plan.

        A throttle part way through the plan still writes the seasons read
        before it, and then refuses the player.
        """
        # One worker per player, so the stats and the matches are one sync
        self.user_app_service.update_w3c_stats(user)

        with Session.begin() as session:
            ledger = {
                row.wc3_season: row
                for row in session.execute(
                    select(
                        col(LadderSync.wc3_season),
                        col(LadderSync.synced_at),
                        col(LadderSync.complete),
                    ).where(col(LadderSync.user_id) == user.id)
                )
            }

        if not user.battleTag:
            raise BadRequestError(f"User {user.id} has no battle tag to sync")
        throttled: W3CThrottledError | None = None
        try:
            if plan.seasons is None:
                matches, complete = w3c_service.walk_player_matches(
                    user.battleTag, plan.walk_from, plan.since
                )
            else:
                wanted = []
                for season in plan.seasons:
                    row = ledger.get(season)
                    is_open = season == plan.open_season
                    if not _read_to_the_end(row, is_open):
                        wanted.append((season, _since_of(row, is_open, plan.since)))
                matches, complete = w3c_service.get_player_matches(
                    user.battleTag, wanted
                )
        except W3CThrottledError as refusal:
            # The seasons read before the refusal are written and stamped, so
            # the next run asks for the ones it never reached
            if refusal.fetched is None:
                raise
            matches, complete = refusal.fetched
            throttled = refusal

        # A worker writes this player alone; writing the opponent's rows too
        # made two workers order the same users in reverse and deadlock
        tag = user.battleTag.lower()
        own = [row for row in matches if row.battleTag.lower() == tag]

        stamp = utcnow()
        with Session.begin() as session:
            self._write_matches(session, user.id, own)
            # The ledger names the seasons this run read; a skipped one keeps
            # the stamp of the run that read it
            for season, done in complete.items():
                self._stamp(session, user.id, season, stamp, done)
            # The stamp says when the app last asked, not that matches were found
            session.execute(
                update(User)
                .where(col(User.id) == user.id)
                .values(ladder_synced_at=stamp)
            )
        if throttled is not None:
            raise throttled

    def _stamp(
        self,
        session: OrmSession,
        user_id: int,
        season: int,
        stamp: datetime,
        complete: bool,
    ) -> None:
        """Record that this player's w3champions season was read just now."""
        row = session.scalar(
            select(LadderSync).where(
                col(LadderSync.user_id) == user_id, col(LadderSync.wc3_season) == season
            )
        )
        if row is None:
            LadderSync.add(
                session,
                {
                    "user_id": user_id,
                    "wc3_season": season,
                    "synced_at": stamp,
                    "complete": complete,
                },
            )
            return
        row.synced_at = stamp
        row.complete = complete

    def _write_matches(
        self, session: OrmSession, user_id: int, rows: list[W3CLadderMatchCreate]
    ) -> None:
        """Insert the matches this player has no row for yet."""
        stored = set(
            session.scalars(
                select(col(W3CLadderMatch.w3c_match_id)).where(
                    col(W3CLadderMatch.user_id) == user_id
                )
            )
        )
        for row in rows:
            if row.w3c_match_id in stored:
                continue
            values = row.model_dump(exclude={"battleTag"}) | {"user_id": user_id}
            try:
                # A savepoint, so a lost race rolls back the insert alone
                with session.begin_nested():
                    W3CLadderMatch.add(session, values)
            except IntegrityError:
                # Another run of the same player wrote the row first
                pass
            stored.add(row.w3c_match_id)


def _window(season: Season) -> tuple[datetime, datetime]:
    """The season as an instant range; a missing date opens that end."""
    return (
        datetime.combine(season.start_date or date.min, time.min, UTC),
        datetime.combine(season.end_date or date.max, time.max, UTC),
    )


def _read_to_the_end(row: Row | None, open_season: bool) -> bool:
    """A closed w3champions season read to its end is never read again.

    The open season always is: it takes new matches after every run.
    """
    return row is not None and row.complete and not open_season


def _since_of(row: Row | None, open_season: bool, start: datetime) -> datetime:
    """The open season is read again from its own stamp; every other season is
    read from the start of the window."""
    return row.synced_at if row is not None and open_season else start


def _w3c_seasons_for(session: OrmSession, season: Season) -> list[int]:
    """The w3champions seasons this GNL window sits in, newest first.

    A window is dated by the matches already stored in it, so a window with
    none names no season and the walk discovers them instead.
    """
    start, end = _window(season)
    return list(
        session.scalars(
            select(col(W3CLadderMatch.wc3_season))
            .where(
                col(W3CLadderMatch.start_time) >= start,
                col(W3CLadderMatch.start_time) <= end,
            )
            .group_by(col(W3CLadderMatch.wc3_season))
            .order_by(col(W3CLadderMatch.wc3_season).desc())
        )
    )


def _stamps(
    session: OrmSession, user_ids: Sequence[int], seasons: Sequence[int] | None
) -> dict[int, datetime | None]:
    """Per player, how fresh his ladder is: the oldest stamp over the
    w3champions seasons the window needs, and None while one of them is unread.

    The all-time answer names no seasons, so it reads every season he has.
    """
    where = [col(LadderSync.user_id).in_(user_ids)]
    if seasons is not None:
        where.append(col(LadderSync.wc3_season).in_(seasons))
    rows = session.execute(
        select(
            col(LadderSync.user_id).label("user_id"),
            func.min(LadderSync.synced_at).label("oldest"),
            func.count().label("read"),
        )
        .where(*where)
        .group_by(col(LadderSync.user_id))
    ).all()
    needed = len(seasons) if seasons is not None else 1
    return {row.user_id: (row.oldest if row.read >= needed else None) for row in rows}


def _season_stamp(
    stamps: dict[int, datetime | None], user_ids: Sequence[int]
) -> datetime | None:
    """The season is as fresh as its least fresh player, and unsynced while one
    rostered player has a season of the window unread."""
    read = [stamps.get(user_id) for user_id in user_ids]
    stamped = [stamp for stamp in read if stamp is not None]
    return min(stamped) if stamped and len(stamped) == len(read) else None


def _walk_start(session: OrmSession, end: datetime) -> int | None:
    """The W3C season the GNL window ends in: the newest stored season that
    began at or before `end`. None while no match is stored."""
    return session.scalar(
        select(col(W3CLadderMatch.wc3_season))
        .group_by(col(W3CLadderMatch.wc3_season))
        .having(func.min(W3CLadderMatch.start_time) <= end)
        .order_by(col(W3CLadderMatch.wc3_season).desc())
        .limit(1)
    )


def _roster(session: OrmSession, season_id: int) -> Sequence[Row]:
    """Everyone signed up for the season, with the team he plays for."""
    return session.execute(
        select(
            col(User.id).label("user_id"),
            col(User.name).label("name"),
            col(User.battleTag).label("battleTag"),
            col(User.country).label("country"),
            col(User.race).label("race"),
            col(Team.id).label("team_id"),
            col(Team.name).label("team_name"),
            col(Team.long_name).label("team_long_name"),
        )
        .join(DBUserSeasonSignup, col(DBUserSeasonSignup.user_id) == User.id)
        .outerjoin(
            DBUserTeamSeason,
            and_(
                col(DBUserTeamSeason.user_id) == col(User.id),
                col(DBUserTeamSeason.season_id) == season_id,
            ),
        )
        .outerjoin(Team, col(Team.id) == DBUserTeamSeason.team_id)
        .where(col(DBUserSeasonSignup.season_id) == season_id)
        .order_by(col(User.id))
    ).all()


def _league_race(season_id: int | None) -> ColumnElement[bool]:
    """A player scores on the race he selected in game, and on no other.

    The league locks a player to one race, so a match on another race is
    practice and pays nothing. The race compared is the selected one, so a
    player registered RANDOM scores on his random picks alone and a player
    registered on a normal race gets no random pick that rolled it. This is
    the rule wc3.no scores by, proven by tests/test_ladder_oracle.

    The race is the one he signed up with that season, so a past season keeps
    its numbers when he registers on another race later. A signup that names
    no race falls back to `users.race`, and so does the all-time answer, which
    spans seasons and has no signup to read.
    """
    race = (
        select(col(User.race))
        .where(col(User.id) == W3CLadderMatch.user_id)
        .scalar_subquery()
    )
    if season_id is not None:
        signup = (
            select(col(DBUserSeasonSignup.race))
            .where(
                col(DBUserSeasonSignup.user_id) == W3CLadderMatch.user_id,
                col(DBUserSeasonSignup.season_id) == season_id,
            )
            .scalar_subquery()
        )
        race = func.coalesce(signup, race)
    return col(W3CLadderMatch.race) == race


def _mmr_scope(
    user_ids: Sequence[int],
    window: tuple[datetime, datetime] | None,
    season_id: int | None,
) -> list[ColumnElement[bool]]:
    """Every match the MMR span reads: these players, on their league race, in
    this window, however short.

    A match too short to score still moves the player's MMR, so the span that
    reports what his MMR did is wider than the scope that pays him for it.
    """
    where: list[ColumnElement[bool]] = [
        col(W3CLadderMatch.user_id).in_(user_ids),
        _league_race(season_id),
    ]
    if window is not None:
        where.append(col(W3CLadderMatch.start_time) >= window[0])
        where.append(col(W3CLadderMatch.start_time) <= window[1])
    return where


def _scope(
    user_ids: Sequence[int],
    window: tuple[datetime, datetime] | None,
    season_id: int | None,
) -> list[ColumnElement[bool]]:
    """The rows one ladder answer scores: the MMR scope, less the matches too
    short to be a game. Points and achievements both read this."""
    return [
        *_mmr_scope(user_ids, window, season_id),
        ladder.counted_clause(col(W3CLadderMatch.duration_s)),
    ]


def _totals(session: OrmSession, scope: list[ColumnElement[bool]]) -> dict[int, Row]:
    """The record and the points of every player, in one group."""
    rows = session.execute(
        select(
            col(W3CLadderMatch.user_id).label("user_id"),
            func.count().label("games"),
            func.sum(case((col(W3CLadderMatch.won), 1), else_=0)).label("wins"),
            func.sum(
                ladder.points_case(
                    col(W3CLadderMatch.won), col(W3CLadderMatch.duration_s)
                )
            ).label("points"),
        )
        .where(*scope)
        .group_by(col(W3CLadderMatch.user_id))
    ).all()
    return {row.user_id: row for row in rows}


def _mmr_span(session: OrmSession, scope: list[ColumnElement[bool]]) -> dict[int, Row]:
    """Where every player's MMR opened, its range, and where it stands.

    Reads the rated matches only. w3champions publishes no MMR for a placement
    match, at either end, so the span runs from the first rated match to the
    last and a player still placing has none at all.
    """
    rated = [*scope, col(W3CLadderMatch.mmr_before).is_not(None)]
    ordered = (
        select(
            col(W3CLadderMatch.user_id).label("user_id"),
            col(W3CLadderMatch.mmr_before).label("mmr_before"),
            col(W3CLadderMatch.mmr_after).label("mmr_after"),
            func.row_number()
            .over(
                partition_by=col(W3CLadderMatch.user_id),
                order_by=(col(W3CLadderMatch.start_time), col(W3CLadderMatch.id)),
            )
            .label("oldest"),
            func.row_number()
            .over(
                partition_by=col(W3CLadderMatch.user_id),
                order_by=(
                    col(W3CLadderMatch.start_time).desc(),
                    col(W3CLadderMatch.id).desc(),
                ),
            )
            .label("newest"),
        )
        .where(*rated)
        .subquery()
    )
    rows = session.execute(
        select(
            ordered.c.user_id.label("user_id"),
            func.max(case((ordered.c.oldest == 1, ordered.c.mmr_before))).label(
                "start"
            ),
            func.max(case((ordered.c.newest == 1, ordered.c.mmr_after))).label(
                "current"
            ),
            func.min(ordered.c.mmr_before).label("min_before"),
            func.max(ordered.c.mmr_before).label("max_before"),
            func.min(ordered.c.mmr_after).label("min_after"),
            func.max(ordered.c.mmr_after).label("max_after"),
        ).group_by(ordered.c.user_id)
    ).all()
    return {row.user_id: row for row in rows}


def _per_day(
    session: OrmSession, scope: list[ColumnElement[bool]]
) -> dict[int, list[Row]]:
    """Every player's days in order, with the MMR he opened and closed each on."""
    day = func.date(W3CLadderMatch.start_time)
    ordered = (
        select(
            col(W3CLadderMatch.user_id).label("user_id"),
            day.label("day"),
            col(W3CLadderMatch.won).label("won"),
            col(W3CLadderMatch.mmr_before).label("mmr_before"),
            col(W3CLadderMatch.mmr_after).label("mmr_after"),
            func.row_number()
            .over(
                partition_by=(col(W3CLadderMatch.user_id), day),
                order_by=(col(W3CLadderMatch.start_time), col(W3CLadderMatch.id)),
            )
            .label("oldest"),
            func.row_number()
            .over(
                partition_by=(col(W3CLadderMatch.user_id), day),
                order_by=(
                    col(W3CLadderMatch.start_time).desc(),
                    col(W3CLadderMatch.id).desc(),
                ),
            )
            .label("newest"),
        )
        .where(*scope)
        .subquery()
    )
    rows = session.execute(
        select(
            ordered.c.user_id.label("user_id"),
            ordered.c.day.label("day"),
            func.sum(case((ordered.c.won, 1), else_=0)).label("wins"),
            func.sum(case((ordered.c.won, 0), else_=1)).label("losses"),
            func.max(case((ordered.c.oldest == 1, ordered.c.mmr_before))).label(
                "first_mmr"
            ),
            func.max(case((ordered.c.newest == 1, ordered.c.mmr_after))).label(
                "last_mmr"
            ),
        )
        .group_by(ordered.c.user_id, ordered.c.day)
        .order_by(ordered.c.user_id, ordered.c.day)
    ).all()
    days: dict[int, list[Row]] = defaultdict(list)
    for row in rows:
        days[row.user_id].append(row)
    return days


def _vs_race(
    session: OrmSession, scope: list[ColumnElement[bool]]
) -> dict[int, dict[str, list[int]]]:
    """Every player's record against each race the opponents selected."""
    rows = session.execute(
        select(
            col(W3CLadderMatch.user_id).label("user_id"),
            col(W3CLadderMatch.opp_race).label("opp_race"),
            func.sum(case((col(W3CLadderMatch.won), 1), else_=0)).label("wins"),
            func.sum(case((col(W3CLadderMatch.won), 0), else_=1)).label("losses"),
        )
        .where(*scope)
        .group_by(col(W3CLadderMatch.user_id), col(W3CLadderMatch.opp_race))
    ).all()
    races: dict[int, dict[str, list[int]]] = defaultdict(_empty_races)
    for row in rows:
        # A match w3champions gave no opponent race for belongs to no bucket
        if row.opp_race is not None:
            races[row.user_id][row.opp_race.value] = [
                int(row.wins or 0),
                int(row.losses or 0),
            ]
    return races


def _by_hour(session: OrmSession, scope: list[ColumnElement[bool]]) -> list[list[int]]:
    """Distinct matches by UTC weekday and hour. Row 0 is Sunday."""
    weekday = extract("dow", col(W3CLadderMatch.start_time))
    hour = extract("hour", col(W3CLadderMatch.start_time))
    rows = session.execute(
        select(
            weekday.label("weekday"),
            hour.label("hour"),
            func.count(distinct(col(W3CLadderMatch.w3c_match_id))).label("games"),
        )
        .where(*scope)
        .group_by(weekday, hour)
    ).all()
    matrix = [[0] * 24 for _ in range(7)]
    for row in rows:
        matrix[int(row.weekday)][int(row.hour)] = int(row.games)
    return matrix


def _games_per_day(
    session: OrmSession, scope: list[ColumnElement[bool]]
) -> dict[date, int]:
    """Distinct matches per UTC day, so a match between two GNL players
    counts once, the way the season total counts it."""
    day = func.date(W3CLadderMatch.start_time)
    rows = session.execute(
        select(
            day.label("day"),
            func.count(distinct(col(W3CLadderMatch.w3c_match_id))).label("games"),
        )
        .where(*scope)
        .group_by(day)
    ).all()
    return {_as_date(row.day): int(row.games or 0) for row in rows}


def _season_days(season: Season, games: dict[date, int]) -> list[LadderSeasonDay]:
    """Every day of the season window, 0 on the days nobody played.

    A season missing a date has no window to draw, so it answers the days it
    has matches on.
    """
    start = season.start_date or (min(games) if games else None)
    end = season.end_date or (max(games) if games else None)
    if start is None or end is None:
        return []
    days = [start + timedelta(days=n) for n in range((end - start).days + 1)]
    return [LadderSeasonDay(d=day, g=games.get(day, 0)) for day in days]


def _match_rows(
    session: OrmSession, scope: list[ColumnElement[bool]]
) -> dict[int, list[W3CLadderMatch]]:
    """Every scoped match, per player, oldest first. One statement for all."""
    rows: dict[int, list[W3CLadderMatch]] = defaultdict(list)
    for match in session.scalars(
        select(W3CLadderMatch)
        .where(*scope)
        .order_by(
            col(W3CLadderMatch.user_id),
            col(W3CLadderMatch.start_time),
            col(W3CLadderMatch.id),
        )
    ):
        rows[match.user_id].append(match)
    return rows


def _coach_tags(session: OrmSession, season_id: int) -> frozenset[str]:
    """The battle tags of every coach of the season, in lower case."""
    tags = session.scalars(
        select(col(User.battleTag))
        .join(DBTeamSeasonCoach, col(DBTeamSeasonCoach.user_id) == col(User.id))
        .where(col(DBTeamSeasonCoach.season_id) == season_id)
    )
    return frozenset(tag.lower() for tag in tags if tag)


def _opponents(roster: Sequence[Row]) -> dict[int, frozenset[str]]:
    """Per player, the tags of everyone signed up on another team."""
    by_team: dict[int | None, set[str]] = defaultdict(set)
    for row in roster:
        if row.battleTag:
            by_team[row.team_id].add(row.battleTag.lower())
    everyone: set[str] = set().union(*by_team.values()) if by_team else set()
    return {row.user_id: frozenset(everyone - by_team[row.team_id]) for row in roster}


def _paid(session: OrmSession, season_id: int | None) -> achievements.PaidSet:
    """What this scope pays for each rule.

    A season reads its own rows; the all-time scope reads the rows that name
    no season. A scope with no rows pays nothing, which is how a season drops
    a rule: by not having one.
    """
    where = (
        col(LadderAchievement.season_id) == season_id
        if season_id is not None
        else col(LadderAchievement.season_id).is_(None)
    )
    rows = session.execute(
        select(col(LadderAchievement.rule_id), col(LadderAchievement.points)).where(
            where
        )
    ).all()
    return {row.rule_id: row.points for row in rows}


def _rules(paid: achievements.PaidSet) -> list[achievements.Achievement]:
    """The catalogue this scope draws, at the prices this scope pays."""
    return [
        replace(rule, points=paid[rule.id])
        for rule in achievements.ACHIEVEMENTS
        if rule.id in paid
    ]


def _earned(
    session: OrmSession,
    scope: list[ColumnElement[bool]],
    roster: Sequence[Row],
    totals: dict[int, Row],
    season_id: int | None,
    paid: achievements.PaidSet,
) -> dict[int, list[achievements.Achievement]]:
    """Every player's achievements, over the rows the totals already read.

    Two statements whatever the number of players: the matches and the
    coaches. A player with no match earns nothing.
    """
    rows = _match_rows(session, scope)
    if not rows:
        return {}
    opponents = _opponents(roster)
    coaches = _coach_tags(session, season_id) if season_id is not None else frozenset()
    tags = {row.user_id: (row.battleTag or "").lower() for row in roster}
    return {
        user_id: achievements.earned(
            matches,
            int(totals[user_id].points or 0) if user_id in totals else 0,
            paid,
            opponents.get(user_id, frozenset()),
            coaches,
            tags.get(user_id, "") in coaches,
        )
        for user_id, matches in rows.items()
    }


def _empty_races() -> dict[str, list[int]]:
    """Every race at 0-0, so the client draws a full row."""
    return {race.value: [0, 0] for race in Race}


def _as_date(value: object) -> date:
    """The day of a group, which Postgres answers as a date and SQLite as text."""
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _mmr(span: Row | None) -> LadderMmr:
    """The MMR the window opened at, its range, and where it stands."""
    if span is None:
        return LadderMmr()
    lows = [v for v in (span.min_before, span.min_after) if v is not None]
    highs = [v for v in (span.max_before, span.max_after) if v is not None]
    return LadderMmr(
        start=span.start,
        min=min(lows) if lows else None,
        max=max(highs) if highs else None,
        current=span.current,
    )


def _player[T: LadderPlayer](
    shape: type[T],
    user: Row,
    total: Row | None,
    span: Row | None,
    days: list[Row],
    races: dict[str, list[int]],
    earned: Sequence[achievements.Achievement] = (),
    synced_at: datetime | None = None,
) -> T:
    """One player row of an answer. A player with no match reads zeros."""
    ladder_points = int(total.points or 0) if total is not None else 0
    return shape(
        id=user.user_id,
        name=user.name,
        battleTag=user.battleTag,
        country=user.country,
        race=user.race,
        points=ladder_points + achievements.total_points(earned),
        ladder_points=ladder_points,
        achievements=list(earned),
        wins=int(total.wins or 0) if total is not None else 0,
        losses=int((total.games or 0) - (total.wins or 0)) if total is not None else 0,
        games=int(total.games or 0) if total is not None else 0,
        mmr=_mmr(span),
        per_day=[
            LadderDay(
                d=_as_date(day.day),
                w=int(day.wins or 0),
                l=int(day.losses or 0),
                mmr=day.last_mmr,
            )
            for day in days
        ],
        vs_race=races or _empty_races(),
        synced_at=synced_at,
    )


def _teams(
    roster: Sequence[Row],
    totals: dict[int, Row],
    spans: dict[int, Row],
    days: dict[int, list[Row]],
    races: dict[int, dict[str, list[int]]],
    earned: dict[int, list[achievements.Achievement]],
    stamps: dict[int, datetime | None],
) -> list[LadderTeam]:
    """The teams of the season, each with the players signed up on it.

    A player signed up on no team of the season joins no team card; his
    matches still count in the season total.
    """
    teams: dict[int, LadderTeam] = {}
    for row in roster:
        if row.team_id is None:
            continue
        team = teams.setdefault(
            row.team_id,
            LadderTeam(
                id=row.team_id, name=row.team_name, long_name=row.team_long_name
            ),
        )
        player = _player(
            LadderPlayer,
            row,
            totals.get(row.user_id),
            spans.get(row.user_id),
            days.get(row.user_id, []),
            races.get(row.user_id, {}),
            earned.get(row.user_id, []),
            stamps.get(row.user_id),
        )
        team.players.append(player)
        team.points += player.points
        team.ladder_points += player.ladder_points
        team.games += player.games
    for team in teams.values():
        team.players.sort(key=lambda player: (-player.points, player.name or ""))
    return sorted(teams.values(), key=lambda team: (-team.points, team.name or ""))


def _matches(
    session: OrmSession, scope: list[ColumnElement[bool]], limit: int, offset: int
) -> list[LadderMatchPublic]:
    """One page of matches, newest first, with the GNL user of each opponent."""
    opponent = aliased(User)
    rows = session.execute(
        select(W3CLadderMatch, col(opponent.id).label("opp_user_id"))
        .outerjoin(
            opponent,
            func.lower(func.trim(opponent.battleTag))
            == func.lower(func.trim(W3CLadderMatch.opp_battletag)),
        )
        .where(*scope)
        .order_by(col(W3CLadderMatch.start_time).desc(), col(W3CLadderMatch.id).desc())
        .offset(offset)
        .limit(limit)
    ).all()

    page = []
    for match, opp_user_id in rows:
        row = LadderMatchPublic.model_validate(match)
        row.opp_user_id = opp_user_id
        page.append(row)
    return page
