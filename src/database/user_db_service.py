from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBUser import DBUser

class UserDBService(AbstractDatabaseService):
    def add(self, name, email):
        session = self.Session()
        user = DBUser.add(session, name=name, email=email)

        # Example usage
        detached_user_dict = user.to_dict()
        session.close()
        print(detached_user_dict)
        return detached_user_dict

    def update(self, user_id, name=None, email=None):
        session = self.Session()
        user = DBUser.update(session, user_id, name=name, email=email)
        session.close()
        return user

    def delete(self, user_id):
        session = self.Session()
        DBUser.delete(session, user_id)
        session.close()

    def get(self, user_id):
        session = self.Session()
        user = session.query(DBUser).filter_by(id=user_id).first()
        session.close()
        return user
