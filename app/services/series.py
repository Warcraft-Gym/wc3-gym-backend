import logging

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.exceptions import DBException, NotFoundException
from app.models.match import DBMatch
from app.models.relationships import DBUserTeamSeason
from app.models.series import DBSeries
from app.models.user import DBUser
from app.schemas.series import Series
from app.schemas.user_team_season_stats import UserTeamSeasonStats
from app.services.base import BaseService
from app.utils.query_util import QueryUtil

logger = logging.getLogger(__name__)


class SeriesService(BaseService):
    def __init__(self, score_app_service, user_app_service):
        self.score_app_service = score_app_service
        self.user_app_service = user_app_service

    def add(self, series: Series):
        with self.get_session() as session:
            series = DBSeries.add(session, series.to_db_dict())
            if not series:
                raise DBException("Series could not be created!")
            return Series.from_dbseries(series)

    def update(self, series: Series):
        with self.get_session() as session:
            series = DBSeries.update(session, series.id, **series.to_db_dict())
            if not series:
                raise NotFoundException("Series not found")
            return Series.from_dbseries(series)

    def delete(self, series_id):
        with self.get_session() as session:
            DBSeries.delete(session, series_id)

    def get(self, series_id):
        with self.get_session() as session:
            # Eager load relationships to avoid N+1 queries, load w3c_stats and team_seasons with season for players
            series = (
                session.scalars(
                    select(DBSeries)
                    .options(
                        joinedload(DBSeries.match).joinedload(DBMatch.team1),
                        joinedload(DBSeries.match).joinedload(DBMatch.team2),
                        joinedload(DBSeries.player1).joinedload(DBUser.w3c_stats),
                        joinedload(DBSeries.player1)
                        .joinedload(DBUser.team_seasons)
                        .joinedload(DBUserTeamSeason.season),
                        joinedload(DBSeries.player2).joinedload(DBUser.w3c_stats),
                        joinedload(DBSeries.player2)
                        .joinedload(DBUser.team_seasons)
                        .joinedload(DBUserTeamSeason.season),
                    )
                    .where(DBSeries.id == series_id)
                )
                .unique()
                .first()
            )
            if not series:
                raise NotFoundException("Series not found")
            return Series.from_dbseries(series)

    def getAll(self):
        with self.get_session() as session:
            result = []
            # Eager load relationships, load w3c_stats and team_seasons with season for players
            series = (
                session.scalars(
                    select(DBSeries).options(
                        joinedload(DBSeries.match).joinedload(DBMatch.team1),
                        joinedload(DBSeries.match).joinedload(DBMatch.team2),
                        joinedload(DBSeries.player1).joinedload(DBUser.w3c_stats),
                        joinedload(DBSeries.player1)
                        .joinedload(DBUser.team_seasons)
                        .joinedload(DBUserTeamSeason.season),
                        joinedload(DBSeries.player2).joinedload(DBUser.w3c_stats),
                        joinedload(DBSeries.player2)
                        .joinedload(DBUser.team_seasons)
                        .joinedload(DBUserTeamSeason.season),
                    )
                )
                .unique()
                .all()
            )
            for single_series in series:
                result.append(Series.from_dbseries(single_series))
            return result

    def search(self, query):
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(DBSeries, query)
            # Eager load related entities, load w3c_stats and team_seasons with season for players
            series_list = (
                session.scalars(
                    select(DBSeries)
                    .options(
                        joinedload(DBSeries.match).joinedload(DBMatch.team1),
                        joinedload(DBSeries.match).joinedload(DBMatch.team2),
                        joinedload(DBSeries.player1).joinedload(DBUser.w3c_stats),
                        joinedload(DBSeries.player1)
                        .joinedload(DBUser.team_seasons)
                        .joinedload(DBUserTeamSeason.season),
                        joinedload(DBSeries.player2).joinedload(DBUser.w3c_stats),
                        joinedload(DBSeries.player2)
                        .joinedload(DBUser.team_seasons)
                        .joinedload(DBUserTeamSeason.season),
                    )
                    .where(filter)
                )
                .unique()
                .all()
                if filter is not None
                else []
            )
            if not series_list:
                logger.debug(f"No series found by searchcriteria: {query}")
                return result
            for series in series_list:
                result.append(Series.from_dbseries(series))
            return result

    def searchForSeasonAndPlayday(self, season_id, playday, query):
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(DBSeries, query)
            series_list = DBSeries.searchForSeasonAndPlayday(
                session, season_id, playday, filter
            )
            if not series_list:
                logger.debug(f"No series found by searchcriteria: {query}")
                return result
            for series in series_list:
                result.append(Series.from_dbseries(series))
            return result

    def searchForSeason(self, season_id, query):
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(DBSeries, query)
            series_list = DBSeries.searchForSeason(session, season_id, filter)
            if not series_list:
                logger.debug(f"No series found by searchcriteria: {query}")
                return result
            for series in series_list:
                result.append(Series.from_dbseries(series))
            return result

    def create_series(self, series: Series):
        series.id = None
        series = self.score_app_service.calculateSeriesScore(series)
        series = self.add(series)
        self.updateGNLSeasonStats(series)
        if not series.player1_points and not series.player2_points:
            return series
        series.match = self.score_app_service.updateMatchScore(series.match_id)

        return series

    def update_series(self, series_id: int, series: Series):
        series.id = series_id
        series = self.score_app_service.calculateSeriesScore(series)
        series = self.update(series)
        self.updateGNLSeasonStats(series)
        if not series.player1_points and not series.player2_points:
            return series

        series.match = self.score_app_service.updateMatchScore(series.match_id)

        return series

    def delete_series(self, series_id: int):
        series = self.get_series(series_id=series_id)
        self.delete(series_id)
        self.updateGNLSeasonStats(series)
        if not series.player1_points and not series.player2_points:
            return
        self.score_app_service.updateMatchScore(series.match_id)

    def get_series(self, series_id: int):
        series_data = self.get(series_id)
        if not series_data:
            raise NotFoundException(f"Series not found byId: {series_id}")
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
