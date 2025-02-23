import logging
import traceback
from src.database.user_db_service import UserDBService
from src.dtos.user_dto import UserDTO
from custom_exceptions import NotFoundException


class UserAppService:
    def __init__(self, user_service: UserDBService):
        self.user_service = user_service

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
