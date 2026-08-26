import logging

from sqlalchemy import func, select

from app.core import fantasy
from app.core.exceptions import NotFoundError
from app.core.ordering import SortOrder, ordered
from app.core.query import QueryElement, QueryUtil
from app.models.match import Match
from app.models.series import (
    SERIES_SORTS,
    Series,
    SeriesCreate,
    SeriesPublic,
    SeriesSort,
    SeriesUpdate,
)
from app.services import derived
from app.services.base import BaseService

logger = logging.getLogger(__name__)


class SeriesService(BaseService):
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

    def search(
        self,
        query: QueryElement | None,
        limit: int | None = None,
        offset: int = 0,
        *,
        sort: SeriesSort | None = None,
        order: SortOrder = "asc",
    ) -> list[SeriesPublic]:
        """The matching series, one page at a time.

        sort names a column of SERIES_SORTS and the series id breaks its ties.
        """
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(Series, query)
            statement = (
                select(Series).options(*Series._list_eager_options()).where(filter)
            )
            if limit is not None or offset:
                # Offset paging is deterministic only with a fixed order
                if sort == "week":
                    statement = statement.join(Match, Match.id == Series.match_id)
                statement = ordered(
                    statement, SERIES_SORTS, sort, order, Series.id
                ).offset(offset)
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

    def fantasy_series_by_week(
        self, season_id: int
    ) -> dict[int | None, list[fantasy.Series]]:
        """Every series of the season, by week, in one statement."""
        with self.get_session() as session:
            return derived.fantasy_series(session, {season_id}).get(season_id, {})

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
        *,
        sort: SeriesSort | None = None,
        order: SortOrder = "asc",
    ) -> list[SeriesPublic]:
        """The matching series of one season, one page at a time.

        sort names a column of SERIES_SORTS and the series id breaks its ties.
        """
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(Series, query)
            series_list = Series.searchForSeason(
                session,
                season_id,
                filter,
                limit=limit,
                offset=offset,
                sort=sort,
                order=order,
            )
            if not series_list:
                logger.debug(f"No series found by searchcriteria: {query}")
                return result
            for series in series_list:
                result.append(SeriesPublic.from_series_reduced(series))
            derived.fill_series(session, result)
            return result
