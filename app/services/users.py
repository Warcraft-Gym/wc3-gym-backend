import logging
from typing import TYPE_CHECKING

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import joinedload

from app.core.exceptions import NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.season import Season
from app.models.team import Team
from app.models.user import User, UserCreate, UserPublic, UserUpdate
from app.models.user_team_season import DBUserTeamSeason, UserTeamSeasonStatsPublic
from app.models.w3c_stats import W3CStats, W3CStatsCreate, W3CStatsPublic
from app.services.base import BaseService
from app.services.w3c import W3CService

if TYPE_CHECKING:
    from app.services.settings import SettingsService

logger = logging.getLogger(__name__)


class UserService(BaseService):
    def __init__(self, settings_app_service: "SettingsService | None" = None) -> None:
        self.settings_app_service = settings_app_service

    def add(self, user: UserCreate) -> UserPublic:
        with self.get_session() as session:
            user = User.add(session, user.model_dump())
            return UserPublic.from_user(user)

    def update(self, user_id: int, user: UserUpdate) -> UserPublic:
        with self.get_session() as session:
            user = User.update(session, user_id, **user.model_dump(exclude_unset=True))
            if not user:
                raise NotFoundError("User not found")
            return UserPublic.from_user(user)

    def delete(self, user_id: int) -> None:
        with self.get_session() as session:
            User.delete(session, user_id)

    def get(self, user_id: int) -> UserPublic | None:
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
                return None
            return UserPublic.from_user(user)

    def search(
        self, query: QueryElement | None, limit: int | None = None, offset: int = 0
    ) -> list[UserPublic]:
        return self._where(
            QueryUtil.convertQueryToDBFilter(User, query), limit=limit, offset=offset
        )

    def find_by_name(self, name: str) -> list[UserPublic]:
        return self._where(User.name == name)

    def find_by_battle_tag(self, battle_tag: str) -> list[UserPublic]:
        return self._where(User.battleTag == battle_tag)

    def find_by_discord_tag(self, discord_tag: str) -> list[UserPublic]:
        return self._where(User.discordTag == discord_tag)

    def find_by_discord_id(self, discord_id: str) -> list[UserPublic]:
        return self._where(User.discordId == discord_id)

    def find_by_discord_id_or_tag(
        self, discord_id: str, discord_tag: str
    ) -> list[UserPublic]:
        return self._where(
            or_(User.discordId == discord_id, User.discordTag == discord_tag)
        )

    def _where(
        self,
        filter: ColumnElement[bool] | None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[UserPublic]:
        with self.get_session() as session:
            result = []
            # Eager load related entities, disable nested loading
            statement = (
                select(User)
                .options(
                    joinedload(User.team_seasons).noload("*"),
                    joinedload(User.w3c_stats),
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
                result.append(UserPublic.from_user(user))
            return result

    def getAll(
        self, limit: int | None = None, offset: int = 0
    ) -> tuple[list[UserPublic], int]:
        """The users, or one page of them, and the total row count."""
        with self.get_session() as session:
            total = session.scalar(select(func.count()).select_from(User)) or 0
            result = []
            # Eager load related entities, disable nested loading
            statement = select(User).options(
                joinedload(User.team_seasons).joinedload(DBUserTeamSeason.season),
                joinedload(User.w3c_stats),
            )
            # Offset paging is deterministic only with a fixed order
            statement = statement.order_by(User.id).offset(offset)
            if limit is not None:
                statement = statement.limit(limit)
            users = session.scalars(statement).unique().all()

            for user in users:
                result.append(UserPublic.from_user(user))
            return result, total

    def createW3CStats(self, w3c_stats: W3CStatsCreate, user_id: int) -> W3CStatsPublic:
        with self.get_session() as session:
            stats = W3CStats.add(
                session, {**w3c_stats.model_dump(), "user_id": user_id}
            )
            return W3CStatsPublic.model_validate(stats)

    def replaceW3CStats(
        self, stats_id: int, user_id: int, w3c_stats: W3CStatsCreate
    ) -> W3CStatsPublic:
        with self.get_session() as session:
            stats = W3CStats.update(
                session, stats_id, **w3c_stats.model_dump(), user_id=user_id
            )
            if not stats:
                raise NotFoundError("W3CStats not found")
            return W3CStatsPublic.model_validate(stats)

    def create_user(self, user: UserCreate) -> UserPublic:
        return self.add(user)

    def update_user(self, user_id: int, user: UserUpdate) -> UserPublic:
        return self.update(user_id, user)

    def delete_user(self, user_id: int) -> None:
        self.delete(user_id)

    def get_user(self, user_id: int) -> UserPublic:
        user_data = self.get(user_id)
        if not user_data:
            raise NotFoundError(f"User not found by Id: {user_id}")
        return user_data

    def validateBattleTag(self, battle_tag: str) -> bool:
        """
        Validate that a BattleTag exists on W3Champions without persisting anything.
        Returns True if player exists, False otherwise.
        """
        w3c_service = W3CService(settings_app_service=self.settings_app_service)
        try:
            return w3c_service.validatePlayer(battle_tag)
        except Exception as e:
            logging.getLogger(__name__).debug(
                f"BattleTag validation failed for {battle_tag}: {e!s}"
            )
            return False

    def updateW3CStats(self, user: UserPublic) -> None:
        w3c_service = W3CService(settings_app_service=self.settings_app_service)

        # Resolve the current W3C season so we can also fetch the previous season
        current_season = None
        if self.settings_app_service:
            season_setting = self.settings_app_service.get_setting("current_wc3_season")
            current_season = season_setting.get("value") if season_setting else None

        all_stats = []

        # Fetch current season stats
        try:
            stats = w3c_service.getPlayerStats(user.battleTag)
            if stats:
                all_stats.extend(stats)
        except Exception as e:
            logging.getLogger(__name__).warning(
                f"Failed to fetch current season W3C stats for {user.battleTag}: {e}"
            )

        # Fetch previous season stats
        if current_season:
            try:
                prev_season = int(current_season) - 1
                prev_stats = w3c_service.getPlayerStats(
                    user.battleTag, season_override=prev_season
                )
                if prev_stats:
                    all_stats.extend(prev_stats)
            except Exception as e:
                logging.getLogger(__name__).warning(
                    f"Failed to fetch previous season W3C stats for {user.battleTag}: {e}"
                )

        for s in all_stats:
            # Records are per race and per season
            existing = [
                u_s
                for u_s in user.w3c_stats
                if u_s.race == s.race and u_s.wc3_season == s.wc3_season
            ]
            for u_s in existing:
                self.replaceW3CStats(u_s.id, u_s.user_id, s)
            if not existing:
                self.createW3CStats(s, user.id)

    def updateW3CStats_ById(self, user_id: int) -> UserPublic:
        user = self.get(user_id)
        if not user:
            raise Exception(f"User could not be found by id: {user_id}")
        self.updateW3CStats(user)
        return self.get_user(user_id)

    def updateUserTeamSeasonStats(
        self, season_stats: UserTeamSeasonStatsPublic
    ) -> UserPublic:
        if not season_stats:
            raise Exception("Seasonstats not defined")
        with self.get_session() as session:
            team = session.get(Team, season_stats.team_id)
            if not team:
                raise Exception(f"Team not found by id: {season_stats.team_id}")
            season = session.get(Season, season_stats.season_id)
            if not season:
                raise Exception(f"Season not found by id: {season_stats.season_id}")
            user = session.get(User, season_stats.user_id)
            if not user:
                raise Exception(f"User not found by id: {season_stats.user_id}")
            uts_obj = session.get(
                DBUserTeamSeason,
                {"team_id": team.id, "season_id": season.id, "user_id": user.id},
            )
            if uts_obj is None:
                uts_obj = DBUserTeamSeason(user=user, season=season, team=team)
                session.add(uts_obj)
            uts_obj.games = season_stats.games
            uts_obj.wins = season_stats.wins
            uts_obj.losses = season_stats.losses
            uts_obj.matchup_history = season_stats.matchup_history
            session.flush()
        return self.get_user(season_stats.user_id)
