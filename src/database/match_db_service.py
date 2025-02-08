from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.GNLMatch import Match

class MatchDBService(AbstractDatabaseService):
    def add(self, team1_id, team2_id, score):
        session = self.Session()
        new_match = Match.add(session, team1_id=team1_id, team2_id=team2_id, score=score)
        session.close()
        return new_match

    def update(self, match_id, score=None):
        session = self.Session()
        updated_match = Match.update(session, match_id, score=score)
        session.close()
        return updated_match

    def delete(self, match_id):
        session = self.Session()
        Match.delete(session, match_id)
        session.close()

    def get(self, match_id):
        session = self.Session()
        match = session.query(Match).filter_by(id=match_id).first()
        session.close()
        return match
