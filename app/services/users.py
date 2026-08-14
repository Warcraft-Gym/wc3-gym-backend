import logging

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.exceptions import NotFoundException
from app.models.user import DBUser
from app.models.w3c_stats import DBW3CStats
from app.schemas.user import User
from app.schemas.user_team_season_stats import UserTeamSeasonStats
from app.schemas.w3c_stats import W3CStats
from app.services.base import BaseService
from app.services.w3c import W3CService
from app.utils.query_util import QueryUtil

logger = logging.getLogger(__name__)


class UserService(BaseService):
    def __init__(self, settings_app_service=None):
        self.settings_app_service = settings_app_service

    def add(self, user: User):
        with self.get_session() as session:
            user = DBUser.add(session, user.to_db_dict())
            return User.from_dbuser(user)

    def update(self, user: User):
        with self.get_session() as session:
            user = DBUser.update(session, user.id, **user.to_db_dict())
            if not user:
                raise NotFoundException("User not found")
            return User.from_dbuser(user)

    def delete(self, user_id):
        with self.get_session() as session:
            DBUser.delete(session, user_id)

    def get(self, user_id):
        with self.get_session() as session:
            # Eager load related entities, disable nested loading
            user = (
                session.scalars(
                    select(DBUser)
                    .options(
                        joinedload(DBUser.team_seasons).noload("*"),
                        joinedload(DBUser.w3c_stats),
                    )
                    .where(DBUser.id == user_id)
                )
                .unique()
                .first()
            )
            if not user:
                return None
            return User.from_dbuser(user)

    def search(self, query):
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(DBUser, query)
            # Eager load related entities, disable nested loading
            users = (
                session.scalars(
                    select(DBUser)
                    .options(
                        joinedload(DBUser.team_seasons).noload("*"),
                        joinedload(DBUser.w3c_stats),
                    )
                    .where(filter)
                )
                .unique()
                .all()
                if filter is not None
                else []
            )
            if not users:
                logger.debug(f"No users found by searchcriteria: {query}")
                return result

            for user in users:
                result.append(User.from_dbuser(user))
            return result

    def getAll(self):
        with self.get_session() as session:
            from app.models.relationships import DBUserTeamSeason

            result = []
            # Eager load related entities, disable nested loading
            users = (
                session.scalars(
                    select(DBUser).options(
                        joinedload(DBUser.team_seasons).joinedload(
                            DBUserTeamSeason.season
                        ),
                        joinedload(DBUser.w3c_stats),
                    )
                )
                .unique()
                .all()
            )

            for user in users:
                result.append(User.from_dbuser(user))
            return result

    def createW3CStats(self, w3c_stats: W3CStats):
        with self.get_session() as session:
            stats = DBW3CStats.add(session, w3c_stats.to_db_dict())
            return W3CStats.from_dbw3cstats(stats)

    def create_user(self, user: User):
        # remove id, db generates the id
        user.id = None
        return self.add(user)

    def update_user(self, user_id, user: User):
        user.id = user_id
        return self.update(user)

    def delete_user(self, user_id: int):
        self.delete(user_id)

    def get_user(self, user_id: int):
        user_data = self.get(user_id)
        if not user_data:
            raise NotFoundException(f"User not found by Id: {user_id}")
        return user_data

    def validateBattleTag(self, battle_tag: str):
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

    def updateW3CStats(self, user: User):
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

        if all_stats:
            for s in all_stats:
                exists = False
                for u_s in user.w3c_stats:
                    # Match by both race AND season to correctly distinguish per-season records
                    if u_s.race == s.race and u_s.wc3_season == s.wc3_season:
                        exists = True
                        s.id = u_s.id
                        s.user_id = u_s.user_id
                        with self.get_session() as session:
                            db_stats = DBW3CStats.update(
                                session, s.id, **s.to_db_dict()
                            )
                            if not db_stats:
                                raise NotFoundException("W3CStats not found")
                            W3CStats.from_dbw3cstats(db_stats)
                if not exists:
                    s.user_id = user.id
                    self.createW3CStats(s)

    def updateW3CStats_ById(self, user_id):
        user = self.get(user_id)
        if not user:
            raise Exception(f"User could not be found by id: {user_id}")
        self.updateW3CStats(user)
        return self.get_user(user_id)

    def updateUserTeamSeasonStats(self, season_stats):
        if not season_stats:
            raise Exception("Seasonstats not defined")
        with self.get_session() as session:
            stats = DBUser.updateUserTeamSeasonStats(session, season_stats)
            UserTeamSeasonStats.from_db_user_team_season(stats)
        return self.get_user(season_stats.user_id)
