from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBTeam import DBTeam

class TeamDBService(AbstractDatabaseService):
    def add(self, name):
        session = self.Session()
        new_team = DBTeam.add(session, name=name)
        session.close()
        return new_team

    def update(self, team_id, name=None):
        session = self.Session()
        updated_team = DBTeam.update(session, team_id, name=name)
        session.close()
        return updated_team

    def delete(self, team_id):
        session = self.Session()
        DBTeam.delete(session, team_id)
        session.close()

    def get(self, team_id):
        session = self.Session()
        team = session.query(DBTeam).filter_by(id=team_id).first()
        session.close()
        return team
