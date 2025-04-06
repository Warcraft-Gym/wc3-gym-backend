import os

from src.database.match_db_service import MatchDBService
from src.database.series_db_service import SeriesDBService
from src.database.team_db_service import TeamDBService
from src.database.team_season_db_service import TeamSeasonDBService
from src.util.query_util import QueryUtil
from src.dtos.series_dto import SeriesDTO
from src.dtos.team_dto import TeamDTO

class ScoreAppService:
    STANDARD_MAX_SCORE = 3
    HELPSTONE_MAX_SCORE = 4

    def __init__(self, match_service: MatchDBService, serires_service:  SeriesDBService, team_service: TeamDBService, team_season_service: TeamSeasonDBService):
        self.match_service = match_service
        self.series_service = serires_service
        self.team_service = team_service
        self.team_season_service = team_season_service

    def calculateSeriesScore(self, series: SeriesDTO):
        try:
            series.player1_points = self.getScoreByMapScore(series.player1_score, series.player2_score)
            series.player2_points = self.getScoreByMapScore(series.player2_score, series.player1_score)
        except Exception as e:
            raise e

        return series

    def updateMatchScore(self, matchId: int):
        match = self.match_service.get(matchId)

        query = QueryUtil.parseQuery('match_id == ' + str(matchId))

        series_list = self.series_service.search(query)

        team1_score = 0
        team2_score = 0

        season_id = 0

        for single_series in series_list:
            if single_series.player1_score is not None and single_series.player2_score is not None: 
                if single_series.player1_points is None or single_series.player2_points is None:
                    single_series = self.calculateSeriesScore(single_series)
                    self.series_service.update(single_series)

            if single_series.player1_points is not None:
                team1_score += single_series.player1_points
            if single_series.player2_points is not None:
                team2_score += single_series.player2_points

        match.team1_score = team1_score
        match.team2_score = team2_score

        match_data = self.match_service.update(matchId, match)

        match_data.team1 =  self.updateTeamScore(match.team1, season_id)
        match_data.team2 =  self.updateTeamScore(match.team2, season_id)
    
        return match_data

    def updateTeamScore(self, team: TeamDTO, seasonId: int):
        team_points = 0
        team_against = 0

        query = QueryUtil.parseQuery("season_id == " + str(seasonId) + " and team1_id == " + str(team.id))
        matches = self.match_service.search(query)

        for match in matches:
            team_points += match.team1_score
            team_against += match.team2_score
        
        query = QueryUtil.parseQuery("season_id == " + str(seasonId) + " and team2_id == " + str(team.id))
        matches = self.match_service.search(query)

        for match in matches:
            team_points += match.team2_score
            team_against += match.team1_score

        season_key = 0

        for i in range(len(team.seasons_info)):
            if team.seasons_info[i].season_id == seasonId:
               season_key = i


        team.seasons_info[season_key].final_score = team_points
        team.seasons_info[season_key].points_against = team_against

        #TODO: This seems to be broken as there can be weeks where a team has less series in a match => double check with shibby for a good aproach
        team.seasons_info[season_key].points_available = (team.seasons_info[season_key].season.series_per_week * team.seasons_info[season_key].season.number_weeks * self.getMaxPointsPerSeries()) - team_points - team_against

        return self.team_season_service.update(team.id, team.seasons_info[season_key])
    
    def getScoreByMapScore(self, playerScore: int, opponentScore: int):
        if playerScore == None and opponentScore == None:
            return None
        if playerScore == None or playerScore < 0 or playerScore > 2:
            raise Exception("Score is not valid please check it.")
        if opponentScore == None or opponentScore < 0 or opponentScore > 2:
            raise Exception("Score is not valid please check it.")

        if playerScore == 0 or playerScore == 1:
            return playerScore
        
        if os.getenv('SCORE_SYSTEM') == 'helpstone':
            return self.getHelpstoneScoreByMapScore(opponentScore)
        
        return self.getStandardScoreByMapScore(opponentScore)

    def getHelpstoneScoreByMapScore(self, opponentScore: int):
        if opponentScore == 0:
            return self.HELPSTONE_MAX_SCORE
        elif opponentScore == 1:
            return (self.HELPSTONE_MAX_SCORE - 1)
        
    
    def getStandardScoreByMapScore(self, opponentScore: int):
        if opponentScore == 0:
            return self.STANDARD_MAX_SCORE
        elif opponentScore == 1:
            return (self.STANDARD_MAX_SCORE - 1)
    
    def getMaxPointsPerSeries(self):
        if os.getenv('SCORE_SYSTEM') == 'helpstone':
            return self.HELPSTONE_MAX_SCORE
        return self.STANDARD_MAX_SCORE
        