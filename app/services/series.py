import logging
from typing import TYPE_CHECKING, NamedTuple

from sqlalchemy import case, func, select
from sqlalchemy.orm import aliased

from app.core.exceptions import NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.match import Match
from app.models.series import Series, SeriesCreate, SeriesPublic, SeriesUpdate
from app.models.user import User
from app.models.user_team_season import UserTeamSeasonStatsPublic
from app.services import derived
from app.services.base import BaseService

if TYPE_CHECKING:
    from app.services.users import UserService

logger = logging.getLogger(__name__)


class CareerSeriesRow(NamedTuple):
    """The seven values a career total reads off one series.

    player1_name and player2_name are the raw user names, null when the
    series points at a user row that is not there.
    """

    player1_id: int | None
    player2_id: int | None
    player1_score: int | None
    player2_score: int | None
    season_id: int | None
    player1_name: str | None
    player2_name: str | None


class SeriesService(BaseService):
    def __init__(self, user_app_service: "UserService") -> None:
        self.user_app_service = user_app_service

    def add(self, series: SeriesCreate) -> SeriesPublic:
        with self.get_session() as session:
            series = Series.add(session, series.model_dump())
            public = SeriesPublic.from_series(series)
            derived.fill_series(session, [public])
            return public

    def update(self, series_id: int, series: SeriesUpdate) -> SeriesPublic:
        with self.get_session() as session:
            series = Series.update(
                session, series_id, **series.model_dump(exclude_unset=True)
            )
            if not series:
                raise NotFoundError("Series not found")
            public = SeriesPublic.from_series(series)
            derived.fill_series(session, [public])
            return public

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
            public = SeriesPublic.from_series(series)
            derived.fill_series(session, [public])
            return public

    def career_stats_rows(self) -> list[CareerSeriesRow]:
        """Every series, as the columns a career total needs.

        One statement and one row per series: the career recalculation
        reads ids, scores, the season and the two player names, so it
        never builds the nested series answer.
        """
        player1 = aliased(User)
        player2 = aliased(User)
        with self.get_session() as session:
            # Outer joins, so a series with no match or no player row stays
            rows = session.execute(
                select(
                    Series.player1_id,
                    Series.player2_id,
                    Series.player1_score,
                    Series.player2_score,
                    Match.season_id,
                    player1.name,
                    player2.name,
                )
                .join(Match, Match.id == Series.match_id, isouter=True)
                .join(player1, player1.id == Series.player1_id, isouter=True)
                .join(player2, player2.id == Series.player2_id, isouter=True)
            ).all()
            return [CareerSeriesRow(*row) for row in rows]

    def search(
        self, query: QueryElement | None, limit: int | None = None, offset: int = 0
    ) -> list[SeriesPublic]:
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(Series, query)
            statement = (
                select(Series).options(*Series._list_eager_options()).where(filter)
            )
            if limit is not None or offset:
                # Offset paging is deterministic only with a fixed order
                statement = statement.order_by(Series.id).offset(offset)
                if limit is not None:
                    statement = statement.limit(limit)
            series_list = session.scalars(statement).all() if filter is not None else []
            if not series_list:
                logger.debug(f"No series found by searchcriteria: {query}")
                return result
            for series in series_list:
                result.append(SeriesPublic.from_series_reduced(series))
            derived.fill_series(session, result)
            return result

    def count(self, query: QueryElement | None) -> int:
        """The number of series that match the query."""
        with self.get_session() as session:
            filter = QueryUtil.convertQueryToDBFilter(Series, query)
            if filter is None:
                return 0
            statement = select(func.count()).select_from(Series).where(filter)
            return session.scalar(statement) or 0

    def countForSeason(self, season_id: int, query: QueryElement | None) -> int:
        """The number of series in one season that match the query."""
        with self.get_session() as session:
            filter = QueryUtil.convertQueryToDBFilter(Series, query)
            statement = (
                select(func.count())
                .select_from(Series)
                .where(Series.match.has(Match.season_id == season_id))
            )
            if filter is not None:
                statement = statement.where(filter)
            return session.scalar(statement) or 0

    def searchForSeasonAndPlayday(
        self,
        season_id: int,
        playday: int,
        query: QueryElement | None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[SeriesPublic]:
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(Series, query)
            series_list = Series.searchForSeasonAndPlayday(
                session, season_id, playday, filter, limit=limit, offset=offset
            )
            if not series_list:
                logger.debug(f"No series found by searchcriteria: {query}")
                return result
            for series in series_list:
                result.append(SeriesPublic.from_series_reduced(series))
            derived.fill_series(session, result)
            return result

    def searchForSeason(
        self,
        season_id: int,
        query: QueryElement | None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[SeriesPublic]:
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(Series, query)
            series_list = Series.searchForSeason(
                session, season_id, filter, limit=limit, offset=offset
            )
            if not series_list:
                logger.debug(f"No series found by searchcriteria: {query}")
                return result
            for series in series_list:
                result.append(SeriesPublic.from_series_reduced(series))
            derived.fill_series(session, result)
            return result

    def create_series(self, series: SeriesCreate) -> SeriesPublic:
        series = self.add(series)
        self.updateGNLSeasonStats(series)
        return series

    def update_series(self, series_id: int, series: SeriesUpdate) -> SeriesPublic:
        series = self.update(series_id, series)
        self.updateGNLSeasonStats(series)
        return series

    def delete_series(self, series_id: int) -> None:
        series = self.get_series(series_id=series_id)
        self.delete(series_id)
        self.updateGNLSeasonStats(series)

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
        """The season record of one player, counted by the database.

        Two statements: the counts come back as one row, and the matchup
        history as one race per series the player is in.
        """
        plays = (Series.player1_id == user_id) | (Series.player2_id == user_id)
        # A series counts once both scores are in and they are not both zero
        scored = (
            Series.player1_score.is_not(None)
            & Series.player2_score.is_not(None)
            & ~((Series.player1_score == 0) & (Series.player2_score == 0))
        )
        # Two games take the series, so every other scored series is a loss
        took_two = ((Series.player1_id == user_id) & (Series.player1_score == 2)) | (
            (Series.player2_id == user_id) & (Series.player2_score == 2)
        )
        opponent = aliased(User)
        with self.get_session() as session:
            # count() skips the null a case with no else leaves behind
            games, wins, losses = session.execute(
                select(
                    func.count(),
                    func.count(case((scored & took_two, 1))),
                    func.count(case((scored & ~took_two, 1))),
                )
                .select_from(Series)
                .join(Match, Match.id == Series.match_id)
                .where(Match.season_id == season_id, plays)
            ).one()
            races = session.scalars(
                select(opponent.race)
                .select_from(Series)
                .join(Match, Match.id == Series.match_id)
                # The opponent is the other player of the series
                .join(
                    opponent,
                    opponent.id
                    == case(
                        (Series.player1_id == user_id, Series.player2_id),
                        else_=Series.player1_id,
                    ),
                )
                .where(Match.season_id == season_id, plays)
                # Playday then series id, so the stored list has one order
                .order_by(Match.playday, Series.id)
            ).all()
        return UserTeamSeasonStatsPublic(
            user_id=user_id,
            games=int(games),
            wins=int(wins),
            losses=int(losses),
            season_id=season_id,
            team_id=team_id,
            matchup_history=[race.value for race in races],
        )
