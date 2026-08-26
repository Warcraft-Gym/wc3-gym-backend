import logging
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import ColumnElement, Select, func, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import joinedload, noload, selectinload

from app.core.exceptions import NotFoundError, W3CThrottledError
from app.core.query import QueryElement, QueryUtil
from app.models.relationships import DBUserSeasonSignup
from app.models.user import User, UserCreate, UserListPublic, UserPublic, UserUpdate
from app.models.w3c_stats import (
    W3CStats,
    W3CStatsCreate,
    W3CSyncFailure,
    W3CSyncResult,
)
from app.services import derived
from app.services.base import BaseService
from app.services.w3c import THROTTLED_MESSAGE, W3CService

if TYPE_CHECKING:
    from app.services.settings import SettingsService

logger = logging.getLogger(__name__)

# Threads that call w3champions at once. The work is network wait, so four
# of them cost no CPU and keep a team of 18 players under five seconds.
W3C_SYNC_WORKERS = 4

# A button absorbs a double click and a second admin, and still refreshes
# a roster before its match.
SYNC_MAX_AGE = timedelta(minutes=10)


def _now() -> datetime:
    """UTC without a zone, the shape the DATETIME columns hold."""
    return datetime.now(UTC).replace(tzinfo=None)


def _public(session: OrmSession, user: User) -> UserPublic:
    """One user, with the season record of every team he played for."""
    public = UserPublic.from_user(user)
    derived.fill_gnl_stats(session, [public])
    return public


class UserService(BaseService):
    def __init__(self, settings_app_service: "SettingsService | None" = None) -> None:
        self.settings_app_service = settings_app_service

    def add(self, user: UserCreate) -> UserPublic:
        with self.get_session() as session:
            user = User.add(session, user.model_dump())
            return _public(session, user)

    def update(self, user_id: int, user: UserUpdate) -> UserPublic:
        with self.get_session() as session:
            user = User.update(session, user_id, **user.model_dump(exclude_unset=True))
            if not user:
                raise NotFoundError("User not found")
            return _public(session, user)

    def delete(self, user_id: int) -> None:
        with self.get_session() as session:
            User.delete(session, user_id)

    def get(self, user_id: int) -> UserPublic:
        with self.get_session() as session:
            # Eager load related entities, disable nested loading
            user = (
                session.scalars(
                    select(User)
                    .options(
                        joinedload(User.team_seasons).noload("*"),
                        joinedload(User.w3c_stats),
                    )
                    .where(User.id == user_id)
                )
                .unique()
                .first()
            )
            if not user:
                raise NotFoundError(f"User not found by Id: {user_id}")
            return _public(session, user)

    def search(
        self, query: QueryElement | None, limit: int | None = None, offset: int = 0
    ) -> list[UserListPublic]:
        return self._where(
            QueryUtil.convert_query_to_db_filter(User, query),
            limit=limit,
            offset=offset,
        )

    def find_by_ids(self, user_ids: Iterable[int | None]) -> list[UserListPublic]:
        """The users of those ids, read in one statement."""
        ids = [user_id for user_id in user_ids if user_id is not None]
        if not ids:
            return []
        return self._where(User.id.in_(ids))

    def find_by_discord_id(self, discord_id: str) -> list[UserListPublic]:
        return self._where(User.discordId == discord_id)

    def find_by_discord_id_or_tag(
        self, discord_id: str, discord_tag: str
    ) -> list[UserListPublic]:
        return self._where(
            or_(User.discordId == discord_id, User.discordTag == discord_tag)
        )

    def _where(
        self,
        filter: ColumnElement[bool] | None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[UserListPublic]:
        with self.get_session() as session:
            result = []
            # The list row has no gnl_stats, so the link rows stay out
            statement = (
                select(User)
                .options(
                    noload(User.team_seasons),
                    joinedload(User.w3c_stats),
                    selectinload(User.signup_seasons).joinedload(
                        DBUserSeasonSignup.season
                    ),
                )
                .where(filter)
            )
            if limit is not None or offset:
                # Offset paging is deterministic only with a fixed order
                statement = statement.order_by(User.id).offset(offset)
                if limit is not None:
                    statement = statement.limit(limit)
            users = (
                session.scalars(statement).unique().all() if filter is not None else []
            )
            if not users:
                logger.debug(f"No users found by searchcriteria: {filter}")
                return result

            for user in users:
                result.append(UserListPublic.from_user(user))
            return result

    def get_all(
        self, limit: int | None = None, offset: int = 0
    ) -> tuple[list[UserListPublic], int]:
        """The users, or one page of them, and the total row count."""
        with self.get_session() as session:
            total = session.scalar(select(func.count()).select_from(User)) or 0
            result = []
            # The list row has no gnl_stats, so the link rows stay out
            statement = select(User).options(
                noload(User.team_seasons),
                joinedload(User.w3c_stats),
                selectinload(User.signup_seasons).joinedload(DBUserSeasonSignup.season),
            )
            # Offset paging is deterministic only with a fixed order
            statement = statement.order_by(User.id).offset(offset)
            if limit is not None:
                statement = statement.limit(limit)
            users = session.scalars(statement).unique().all()

            for user in users:
                result.append(UserListPublic.from_user(user))
            return result, total

    def validate_battle_tag(self, battle_tag: str) -> bool:
        """
        Validate that a BattleTag exists on W3Champions without persisting anything.
        Returns True if player exists, False otherwise.
        """
        w3c_service = W3CService(settings_app_service=self.settings_app_service)
        try:
            return w3c_service.validate_player(battle_tag)
        except Exception as e:
            logging.getLogger(__name__).debug(
                f"BattleTag validation failed for {battle_tag}: {e!s}"
            )
            return False

    def update_w3c_stats(self, user: UserListPublic) -> None:
        w3c_service = W3CService(settings_app_service=self.settings_app_service)

        # Resolve the season once, so both fetches agree and w3champions is
        # asked for the season list at most once per player.
        try:
            current_season = w3c_service.current_season()
        except Exception as e:
            logger.warning(f"No W3C season to sync {user.battleTag} against: {e}")
            raise

        seasons = (current_season, current_season - 1)
        all_stats = []
        refusals: list[Exception] = []
        for season in seasons:
            try:
                stats = w3c_service.get_player_stats(
                    user.battleTag, season_override=season
                )
                if stats:
                    all_stats.extend(stats)
            except W3CThrottledError:
                raise
            except Exception as e:
                logger.warning(
                    f"Failed to fetch season {season} W3C stats for {user.battleTag}: {e}"
                )
                refusals.append(e)

        # A season that answers nothing is an unranked player, so only a sync
        # w3champions refused for every season is a failure the caller reports.
        if len(refusals) == len(seasons):
            raise refusals[0]

        # One transaction reads and writes the rows of this player, so no
        # other sync can insert between the read and the write.
        with self.get_session() as session:
            for s in all_stats:
                self._write_w3c_stats(session, user.id, s)
            # The stamp says when the app last asked, not that stats were found
            session.execute(
                update(User).where(User.id == user.id).values(w3c_synced_at=_now())
            )

    def sync_w3c_stats_users(
        self, users: list[UserListPublic], max_age: timedelta
    ) -> W3CSyncResult:
        """Sync these players in parallel and report every one of them.

        A player synced more recently than max_age is skipped untouched; a
        max_age of zero syncs everyone.
        """
        result = W3CSyncResult()
        fresh_since = _now() - max_age
        pending = []
        for user in users:
            if user.w3c_synced_at and user.w3c_synced_at > fresh_since:
                result.skipped.append(user.id)
            else:
                pending.append(user)
        if not pending:
            return result

        synced: set[int] = set()
        failures: dict[int, str] = {}
        throttled = False

        # Each worker opens its own session; the threads share the engine only
        with ThreadPoolExecutor(W3C_SYNC_WORKERS) as pool:
            futures = {pool.submit(self.update_w3c_stats, u): u for u in pending}
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
                    # The reason reaches the client, so it names no statement
                    reason = (
                        "Database error" if isinstance(e, SQLAlchemyError) else str(e)
                    )
                    failures[user.id] = reason
                    logger.warning(
                        f"Failed to sync W3C stats for user {user.name} "
                        f"(BattleTag: {user.battleTag}): {reason}"
                    )
                else:
                    synced.add(user.id)

        if throttled:
            stopped = [
                u for u in pending if u.id not in synced and u.id not in failures
            ]
            for u in stopped:
                failures[u.id] = THROTTLED_MESSAGE
            logger.warning(
                f"W3Champions throttled the sync, {len(stopped)} player(s) not synced"
            )

        # The report follows the order the caller passed, not the order the
        # workers finished in.
        for user in pending:
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

    def _write_w3c_stats(
        self, session: OrmSession, user_id: int, w3c_stats: W3CStatsCreate
    ) -> None:
        """Update the row of this race and season, or insert it."""
        values = {**w3c_stats.model_dump(), "user_id": user_id}
        existing = session.scalars(self._w3c_stats_key(user_id, w3c_stats)).all()
        if existing:
            for row in existing:
                W3CStats.update_object(session, row, **values)
            return
        try:
            # A savepoint, so a lost race rolls back the insert alone
            with session.begin_nested():
                W3CStats.add(session, values)
        except IntegrityError:
            # Another sync inserted the row first, so update that row
            row = session.scalars(
                self._w3c_stats_key(user_id, w3c_stats).with_for_update()
            ).first()
            if row is None:
                raise
            W3CStats.update_object(session, row, **values)

    @staticmethod
    def _w3c_stats_key(
        user_id: int, w3c_stats: W3CStatsCreate
    ) -> Select[tuple[W3CStats]]:
        """The rows the unique index holds to one: user, race and season."""
        return select(W3CStats).where(
            W3CStats.user_id == user_id,
            W3CStats.race == w3c_stats.race,
            W3CStats.wc3_season == w3c_stats.wc3_season,
        )

    def update_w3c_stats_by_id(self, user_id: int) -> UserPublic:
        self.update_w3c_stats(self.get(user_id))
        return self.get(user_id)
