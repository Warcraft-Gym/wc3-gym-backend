import logging
import traceback
from src.database.user_db_service import UserDBService
from src.dtos.user_dto import UserDTO
from custom_exceptions import NotFoundException


class UserAppService:
    def __init__(self, user_service: UserDBService):
        self.user_service = user_service

    def create_user(self, user : UserDTO):
        user_data = self.user_service.add(user)
        if(user_data):
            user_data = user_data.to_dict()
        return user_data

    def update_user(self, user : UserDTO):
        user_data = self.user_service.update(user)
        if(user_data):
            user_data = user_data.to_dict()
        return user_data

    def delete_user(self, user_id: int):
        self.user_service.delete(user_id)

    def get_user(self, user_id: int):
        user_data = self.user_service.get(user_id)
        if not user_data:
            raise NotFoundException(f"User not found by Id: {user_id}")
        return user_data.to_dict()
            
    def getAll(self):
        users_data = self.user_service.getAll()
        user_dict_l = []
        for ud in users_data:
            user_dict_l.append(ud.to_dict())
        return user_dict_l

    def search(self, query):
        users_data = self.user_service.search(query)
        user_dict_l = []
        for ud in users_data:
            user_dict_l.append(ud.to_dict())
        return user_dict_l
