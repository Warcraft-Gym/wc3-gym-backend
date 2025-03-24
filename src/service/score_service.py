from src.database.match_db_service import MatchDBService
from src.database.series_db_service import SeriesDBService

class ScoreAPPService:
    def __init__(self, match_service: MatchDBService, serires_service:  SeriesDBService):
        self.match_service = match_service
        self.series_service = serires_service

    def updateMatchScore(self, matchId: int):
        match = self.match_service.get(matchId).to_db_dict()

        series = self.series_service.search('match_id == ' + matchId)

        team1_score = 0
        team2_score = 0

        for single_series in series:
            team1_score += single_series.to_db_dict()['player1_score']
            team2_score += single_series.to_db_dict()['player2_score']

        match['team1_score'] = team1_score
        match['team2_score'] = team2_score

        self.match_service.update(matchId, match)        
        