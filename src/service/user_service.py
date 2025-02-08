from src.database.user_db_service import UserDBService
from src.dtos.user_dto import UserDTO

class UserAppService:
    def __init__(self, user_service: UserDBService):
        self.user_service = user_service

    def create_user(self, name: str, email: str):
        user_data = self.user_service.add(name=name, email=email)
        user_dto = UserDTO.from_dict(user_data)
        return user_dto.to_dict()

    def update_user(self, user_id: int, name: str = None, email: str = None):
        user_data = self.user_service.update(user_id, name=name, email=email)
        user_dto = UserDTO.from_dict(user_data)
        return user_dto.to_dict()

    def delete_user(self, user_id: int):
        self.user_service.delete(user_id)

    def get_user(self, user_id: int):
        user_data = self.user_service.get(user_id)
        user_dto = UserDTO.from_dict(user_data)
        return user_dto.to_dict()
