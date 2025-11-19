import logging
import traceback
from src.database.user_db_service import UserDBService
from src.dtos.user_dto import UserDTO
from custom_exceptions import NotFoundException
from src.service.w3champions.w3c_service import W3CService


class UserAppService:
    def __init__(self, user_service: UserDBService, settings_app_service=None):
        self.user_service = user_service
        self.settings_app_service = settings_app_service

    def create_user(self, user : UserDTO):
        #remove id, db generates the id
        user.id = None
        user_data = self.user_service.add(user)
        return user_data

    def update_user(self, user_id, user : UserDTO):
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

    def updateW3CStats(self, user: UserDTO):
        w3c_service = W3CService(settings_app_service=self.settings_app_service)
        stats = w3c_service.getPlayerStats(user.battleTag)
        if stats:
            for s in stats:
                exists = False
                for u_s in user.w3c_stats:
                    if u_s.race == s.race:
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