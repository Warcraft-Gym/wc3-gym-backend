import logging

from custom_exceptions import NotFoundException
from src.database.user_db_service import UserDBService
from src.schemas.user import User
from src.service.w3champions.w3c_service import W3CService


class UserAppService:
    def __init__(self, user_service: UserDBService, settings_app_service=None):
        self.user_service = user_service
        self.settings_app_service = settings_app_service

    def create_user(self, user: User):
        # remove id, db generates the id
        user.id = None
        user_data = self.user_service.add(user)
        return user_data

    def update_user(self, user_id, user: User):
        user.id = user_id
        user_data = self.user_service.update(user)
        return user_data

    def delete_user(self, user_id: int):
        self.user_service.delete(user_id)

    def get_user(self, user_id: int):
        user_data = self.user_service.get(user_id)
        if not user_data:
            raise NotFoundException(f"User not found by Id: {user_id}")
        return user_data

    def getAll(self):
        users_data = self.user_service.getAll()
        return users_data

    def search(self, query):
        users_data = self.user_service.search(query)
        return users_data

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
                        self.user_service.updateW3CStats(s)
                if not exists:
                    s.user_id = user.id
                    self.user_service.createW3CStats(s)

    def updateW3CStats_ById(self, user_id):
        user = self.user_service.get(user_id)
        if not user:
            raise Exception(f"User could not be found by id: {user_id}")
        self.updateW3CStats(user)
        return self.get_user(user_id)

    def updateUserTeamSeasonStats(self, season_stats):
        if not season_stats:
            raise Exception("Seasonstats not defined")
        self.user_service.updateUserTeamSeasonStats(season_stats)
        return self.get_user(season_stats.user_id)
