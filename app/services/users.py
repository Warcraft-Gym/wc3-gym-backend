import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import ColumnElement, Select, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import joinedload, noload, selectinload
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import NotFoundError, W3CThrottledError
from app.core.query import QueryElement, QueryUtil
from app.models.relationships import DBUserSeasonSignup
from app.models.user import (
    User,
    UserCreate,
    UserListPublic,
    UserPublic,
    UserReduced,
    UserUpdate,
)
from app.models.w3c_stats import (
    W3CStats,
    W3CStatsCreate,
)
from app.services import derived
from app.services.w3c import W3CService

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


class UserService:
    def __init__(self, settings_app_service: "SettingsService | None" = None) -> None:
        self.settings_app_service = settings_app_service

    def add(self, user: UserCreate) -> UserPublic:
        with Session.begin() as session:
            user = User.add(session, user.model_dump())
            return _public(session, user)

    def update(self, user_id: int, user: UserUpdate) -> UserPublic:
        with Session.begin() as session:
            user = User.update(session, user_id, **user.model_dump(exclude_unset=True))
            if not user:
                raise NotFoundError("User not found")
            return _public(session, user)

    def delete(self, user_id: int) -> None:
        with Session.begin() as session:
            User.delete(session, user_id)

    def get(self, user_id: int) -> UserPublic:
        with Session.begin() as session:
            # Eager load related entities, disable nested loading
            user = (
                session.scalars(
                    select(User)
                    .options(
                        joinedload(User.team_seasons).noload("*"),
                        joinedload(User.w3c_stats),
                    )
                    .where(col(User.id) == user_id)
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
        return self._where(col(User.id).in_(ids))

    def find_by_discord_id(self, discord_id: str) -> list[UserListPublic]:
        return self._where(col(User.discordId) == discord_id)

    def find_by_discord_id_or_tag(
        self, discord_id: str, discord_tag: str
    ) -> list[UserListPublic]:
        return self._where(
            or_(col(User.discordId) == discord_id, col(User.discordTag) == discord_tag)
        )

    def _where(
        self,
        filter: ColumnElement[bool] | None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[UserListPublic]:
        with Session.begin() as session:
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
                statement = statement.order_by(col(User.id)).offset(offset)
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
        with Session.begin() as session:
            total = session.scalar(select(func.count()).select_from(User)) or 0
            result = []
            # The list row has no gnl_stats, so the link rows stay out
            statement = select(User).options(
                noload(User.team_seasons),
                joinedload(User.w3c_stats),
                selectinload(User.signup_seasons).joinedload(DBUserSeasonSignup.season),
            )
            # Offset paging is deterministic only with a fixed order
            statement = statement.order_by(col(User.id)).offset(offset)
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
            logger.debug(f"BattleTag validation failed for {battle_tag}: {e!s}")
            return False

    def update_w3c_stats(self, user: UserReduced) -> None:
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
        with Session.begin() as session:
            for s in all_stats:
                self._write_w3c_stats(session, user.id, s)
            # The stamp says when the app last asked, not that stats were found
            session.execute(
                update(User).where(col(User.id) == user.id).values(w3c_synced_at=_now())
            )

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
            col(W3CStats.user_id) == user_id,
            col(W3CStats.race) == w3c_stats.race,
            col(W3CStats.wc3_season) == w3c_stats.wc3_season,
        )

    def update_w3c_stats_by_id(self, user_id: int) -> UserPublic:
        self.update_w3c_stats(self.get(user_id))
        return self.get(user_id)
