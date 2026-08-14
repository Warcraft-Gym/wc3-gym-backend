from app.database.series_db_service import SeriesDBService
from app.exceptions import NotFoundException
from app.schemas.series import Series
from app.schemas.user_team_season_stats import UserTeamSeasonStats
from app.service.score_service import ScoreAppService
from app.service.user_service import UserAppService
from app.util.query_util import QueryUtil


class SeriesAppService:
    def __init__(
        self,
        series_service: SeriesDBService,
        score_app_service: ScoreAppService,
        user_app_service: UserAppService,
    ):
        self.series_service = series_service
        self.score_app_service = score_app_service
        self.user_app_service = user_app_service

    def create_series(self, series: Series):
        series.id = None
        series = self.score_app_service.calculateSeriesScore(series)
        series = self.series_service.add(series)
        self.updateGNLSeasonStats(series)
        if not series.player1_points and not series.player2_points:
            return series
        series.match = self.score_app_service.updateMatchScore(series.match_id)

        return series

    def update_series(self, series_id: int, series: Series):
        series.id = series_id
        series = self.score_app_service.calculateSeriesScore(series)
        series = self.series_service.update(series)
        self.updateGNLSeasonStats(series)
        if not series.player1_points and not series.player2_points:
            return series

        series.match = self.score_app_service.updateMatchScore(series.match_id)

        return series

    def delete_series(self, series_id: int):
        series = self.get_series(series_id=series_id)
        self.series_service.delete(series_id)
        self.updateGNLSeasonStats(series)
        if not series.player1_points and not series.player2_points:
            return
        self.score_app_service.updateMatchScore(series.match_id)

    def get_series(self, series_id: int):
        series_data = self.series_service.get(series_id)
        if not series_data:
            raise NotFoundException(f"Series not found byId: {series_id}")
        return series_data

    def getAll(self):
        series_data = self.series_service.getAll()
        return series_data

    def search(self, query):
        series_data = self.series_service.search(query)
        return series_data

    def searchForSeason(self, season_id, query):
        series_data = self.series_service.searchForSeason(season_id, query)
        return series_data

    def searchForSeasonAndPlayday(self, season_id, playday, query):
        series_data = self.series_service.searchForSeasonAndPlayday(
            season_id, playday, query
        )
        return series_data

    def updateGNLSeasonStats(self, series):
        p1_season_data = self.calculateUserSeasonStats(
            series.player1.id, series.match.season_id, series.match.team1_id
        )
        self.user_app_service.updateUserTeamSeasonStats(p1_season_data)
        p2_season_data = self.calculateUserSeasonStats(
            series.player2.id, series.match.season_id, series.match.team2_id
        )
        self.user_app_service.updateUserTeamSeasonStats(p2_season_data)

    def calculateUserSeasonStats(self, user_id, season_id, team_id):
        query = QueryUtil.parseQuery(
            f"player1_id == {user_id} or player2_id == {user_id}"
        )
        series = self.searchForSeason(season_id, query)
        games = 0
        wins = 0
        losses = 0
        matchup_history = []
        if series:
            games = len(series)
            wins = 0
            losses = 0
            for s in series:
                isWon = self.isSeriesWon(user_id, s)
                if isWon is not None:
                    if isWon:
                        wins += 1
                    else:
                        losses += 1
                # Collect opponent race for matchup history
                if s.player1_id == user_id and s.player2 and s.player2.race:
                    # Convert Race enum to string value if needed
                    race_value = (
                        s.player2.race.value
                        if hasattr(s.player2.race, "value")
                        else s.player2.race
                    )
                    matchup_history.append(race_value)
                elif s.player2_id == user_id and s.player1 and s.player1.race:
                    # Convert Race enum to string value if needed
                    race_value = (
                        s.player1.race.value
                        if hasattr(s.player1.race, "value")
                        else s.player1.race
                    )
                    matchup_history.append(race_value)
        return UserTeamSeasonStats(
            {
                "user_id": user_id,
                "games": games,
                "wins": wins,
                "losses": losses,
                "season_id": season_id,
                "team_id": team_id,
                "matchup_history": matchup_history,
            }
        )

    def isSeriesWon(self, user_id, series):
        if series.player1_score is not None and series.player2_score is not None:
            if series.player1_score == 0 and series.player2_score == 0:
                return None
            if series.player1_id == user_id and series.player1_score == 2:
                return True
            return bool(series.player2_id == user_id and series.player2_score == 2)
        else:
            return None
