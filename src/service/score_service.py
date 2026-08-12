import os

from src.database.match_db_service import MatchDBService
from src.database.series_db_service import SeriesDBService
from src.database.team_db_service import TeamDBService
from src.database.team_season_db_service import TeamSeasonDBService
from src.database.season_db_service import SeasonDBService
from src.database.settings_db_service import SettingsDBService
from src.util.query_util import QueryUtil
from src.schemas.series import Series
from src.schemas.team import Team, TeamReduced

class ScoreAppService:
    STANDARD_MAX_SCORE = 3
    HELPSTONE_MAX_SCORE = 4

    def __init__(self, match_service: MatchDBService, serires_service:  SeriesDBService, team_service: TeamDBService, team_season_service: TeamSeasonDBService, season_service: SeasonDBService, settings_service: SettingsDBService):
        self.match_service = match_service
        self.series_service = serires_service
        self.team_service = team_service
        self.team_season_service = team_season_service
        self.season_service = season_service
        self.settings_service = settings_service

    def calculateSeriesScore(self, series: Series):
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

        match_data.team1 =  self.updateTeamScore(match.team1, match.season_id)
        match_data.team2 =  self.updateTeamScore(match.team2, match.season_id)
    
        return match_data

    def updateTeamScore(self, team: Team | TeamReduced, seasonId: int):
        # A match carries reduced team objects without seasons_info;
        # fetch the full team data in that case
        if not getattr(team, 'seasons_info', None):
            team = self.team_service.get(team.id)
        
        # If still no seasons_info, we can't update the team score
        if team.seasons_info is None or len(team.seasons_info) == 0:
            return team
        
        team_points = 0
        team_against = 0

        query = QueryUtil.parseQuery(f"season_id == {seasonId} and team1_id == {team.id} or season_id == {seasonId} and team2_id == {team.id}")
        matches = self.match_service.search(query)

        for match in matches:
            if match.team1_id == team.id:
                if match.team1_score is not None:
                    team_points += match.team1_score
                if match.team2_score is not None:
                    team_against += match.team2_score
            elif match.team2_id == team.id:
                if match.team2_score is not None:
                    team_points += match.team2_score
                if match.team1_score is not None:
                    team_against += match.team1_score
            else:
                raise Exception("Cannot calculate Teamscore invalid match!")
        
        season_key = None

        for i in range(len(team.seasons_info)):
            if team.seasons_info[i].season_id == seasonId:
               season_key = i


        if season_key is None:
            return team

        team.seasons_info[season_key].final_score = team_points
        team.seasons_info[season_key].points_against = team_against

        # Fetch season directly to get series_per_week and number_weeks
        season = self.season_service.get(seasonId)
        if season is not None and season.series_per_week is not None and season.number_weeks is not None:
            max_available = season.series_per_week * season.number_weeks * self.getMaxPointsPerSeries()
            team.seasons_info[season_key].points_available = max_available - team_points - team_against

        updated_season_info = self.team_season_service.update(team.id, team.seasons_info[season_key])
        
        team.seasons_info[season_key] = updated_season_info
        return team
    
    def _get_score_system(self):
        """Get the score system from settings, fallback to environment variable, default to 'standard'"""
        try:
            score_system_setting = self.settings_service.get_by_key('score_system')
            if score_system_setting and score_system_setting.value:
                return score_system_setting.value
        except:
            pass
        
        # Fallback to environment variable for backward compatibility
        return os.getenv('SCORE_SYSTEM', 'standard')

    def getScoreByMapScore(self, playerScore: int, opponentScore: int):
        if playerScore == None and opponentScore == None:
            return None
        if playerScore == None or playerScore < 0 or playerScore > 2:
            raise Exception("Score is not valid please check it.")
        if opponentScore == None or opponentScore < 0 or opponentScore > 2:
            raise Exception("Score is not valid please check it.")

        if playerScore == 0 or playerScore == 1:
            return playerScore
        
        if self._get_score_system() == 'helpstone':
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
        if self._get_score_system() == 'helpstone':
            return self.HELPSTONE_MAX_SCORE
        return self.STANDARD_MAX_SCORE
        