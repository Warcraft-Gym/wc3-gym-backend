import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.exceptions import NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.series import Series, SeriesCreate, SeriesPublic, SeriesUpdate
from app.models.user_team_season import UserTeamSeasonStatsPublic
from app.services.base import BaseService

if TYPE_CHECKING:
    from app.services.scores import ScoreService
    from app.services.users import UserService

logger = logging.getLogger(__name__)


class SeriesService(BaseService):
    def __init__(
        self, score_app_service: "ScoreService", user_app_service: "UserService"
    ) -> None:
        self.score_app_service = score_app_service
        self.user_app_service = user_app_service

    def add(self, series: SeriesCreate) -> SeriesPublic:
        with self.get_session() as session:
            series = Series.add(session, series.model_dump())
            return SeriesPublic.from_series(series)

    def update(self, series_id: int, series: SeriesUpdate) -> SeriesPublic:
        with self.get_session() as session:
            series = Series.update(
                session, series_id, **series.model_dump(exclude_unset=True)
            )
            if not series:
                raise NotFoundError("Series not found")
            return SeriesPublic.from_series(series)

    def delete(self, series_id: int) -> None:
        with self.get_session() as session:
            Series.delete(session, series_id)

    def get(self, series_id: int) -> SeriesPublic:
        with self.get_session() as session:
            series = session.scalars(
                select(Series)
                .options(*Series._eager_options())
                .where(Series.id == series_id)
            ).first()
            if not series:
                raise NotFoundError("Series not found")
            return SeriesPublic.from_series(series)

    def getAll(self) -> list[SeriesPublic]:
        with self.get_session() as session:
            result = []
            series = session.scalars(
                select(Series).options(*Series._eager_options())
            ).all()
            for single_series in series:
                result.append(SeriesPublic.from_series(single_series))
            return result

    def search(self, query: QueryElement | None) -> list[SeriesPublic]:
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(Series, query)
            series_list = (
                session.scalars(
                    select(Series).options(*Series._eager_options()).where(filter)
                ).all()
                if filter is not None
                else []
            )
            if not series_list:
                logger.debug(f"No series found by searchcriteria: {query}")
                return result
            for series in series_list:
                result.append(SeriesPublic.from_series(series))
            return result

    def searchForSeasonAndPlayday(
        self, season_id: int, playday: int, query: QueryElement | None
    ) -> list[SeriesPublic]:
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(Series, query)
            series_list = Series.searchForSeasonAndPlayday(
                session, season_id, playday, filter
            )
            if not series_list:
                logger.debug(f"No series found by searchcriteria: {query}")
                return result
            for series in series_list:
                result.append(SeriesPublic.from_series(series))
            return result

    def searchForSeason(
        self, season_id: int, query: QueryElement | None
    ) -> list[SeriesPublic]:
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(Series, query)
            series_list = Series.searchForSeason(session, season_id, filter)
            if not series_list:
                logger.debug(f"No series found by searchcriteria: {query}")
                return result
            for series in series_list:
                result.append(SeriesPublic.from_series(series))
            return result

    def create_series(self, series: SeriesCreate) -> SeriesPublic:
        series = self.score_app_service.calculateSeriesScore(series)
        series = self.add(series)
        self.updateGNLSeasonStats(series)
        if not series.player1_points and not series.player2_points:
            return series
        series.match = self.score_app_service.updateMatchScore(series.match_id)

        return series

    def update_series(self, series_id: int, series: SeriesUpdate) -> SeriesPublic:
        series = self.score_app_service.calculateSeriesScore(series)
        series = self.update(series_id, series)
        self.updateGNLSeasonStats(series)
        if not series.player1_points and not series.player2_points:
            return series

        series.match = self.score_app_service.updateMatchScore(series.match_id)

        return series

    def delete_series(self, series_id: int) -> None:
        series = self.get_series(series_id=series_id)
        self.delete(series_id)
        self.updateGNLSeasonStats(series)
        if not series.player1_points and not series.player2_points:
            return
        self.score_app_service.updateMatchScore(series.match_id)

    def get_series(self, series_id: int) -> SeriesPublic:
        series_data = self.get(series_id)
        if not series_data:
            raise NotFoundError(f"Series not found byId: {series_id}")
        return series_data

    def updateGNLSeasonStats(self, series: SeriesPublic) -> None:
        p1_season_data = self.calculateUserSeasonStats(
            series.player1.id, series.match.season_id, series.match.team1_id
        )
        self.user_app_service.updateUserTeamSeasonStats(p1_season_data)
        p2_season_data = self.calculateUserSeasonStats(
            series.player2.id, series.match.season_id, series.match.team2_id
        )
        self.user_app_service.updateUserTeamSeasonStats(p2_season_data)

    def calculateUserSeasonStats(
        self, user_id: int, season_id: int, team_id: int
    ) -> UserTeamSeasonStatsPublic:
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
        return UserTeamSeasonStatsPublic(
            user_id=user_id,
            games=games,
            wins=wins,
            losses=losses,
            season_id=season_id,
            team_id=team_id,
            matchup_history=matchup_history,
        )

    def isSeriesWon(self, user_id: int, series: SeriesPublic) -> bool | None:
        if series.player1_score is not None and series.player2_score is not None:
            if series.player1_score == 0 and series.player2_score == 0:
                return None
            if series.player1_id == user_id and series.player1_score == 2:
                return True
            return bool(series.player2_id == user_id and series.player2_score == 2)
        else:
            return None
