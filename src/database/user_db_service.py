from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.GymUser import GymUser

class UserDBService(AbstractDatabaseService):
    def add(self, name, email):
        session = self.Session()
        user = GymUser.add(session, name=name, email=email)
        user_data = {
            'id': user.id,
            'name': user.name,
            'email': user.email
        }
        session.close()
        return user_data

    def update(self, user_id, name=None, email=None):
        session = self.Session()
        user = GymUser.update(session, user_id, name=name, email=email)
        user_data = {
            'id': user.id,
            'name': user.name,
            'email': user.email
        }
        session.close()
        return user_data

    def delete(self, user_id):
        session = self.Session()
        GymUser.delete(session, user_id)
        session.close()

    def get(self, user_id):
        session = self.Session()
        user = session.query(GymUser).filter_by(id=user_id).first()
        user_data = {
            'id': user.id,
            'name': user.name,
            'email': user.email
        }
        session.close()
        return user_data
