from sqlalchemy import func, select
from sqlmodel import col

from app.core import fantasy
from app.core.db import Session
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.ordering import SortOrder, ordered
from app.core.query import QueryElement, QueryUtil
from app.core.scoring import wins_needed
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


def _both_scores(row: Series) -> None:
    """A result is both map scores or neither, and neither above the maps a
    win takes in this season: points() has no value for a half or over result."""
    if (row.player1_score is None) != (row.player2_score is None):
        raise BadRequestError("A result needs both map scores")
    if row.player1_score is None or row.player2_score is None:
        return
    wins = wins_needed(row.match.season.map_rules if row.match else None)
    if max(row.player1_score, row.player2_score) > wins or (
        row.player1_score == row.player2_score == wins
    ):
        raise BadRequestError(f"A series of this season ends at {wins} map wins")


class SeriesService:
    def add(self, series: SeriesCreate) -> SeriesPublic:
        with Session.begin() as session:
            row = Series.add(session, series.model_dump())
            _both_scores(row)
            public = SeriesPublic.from_series(row)
            derived.fill_series(session, [public])
            return public

    def update(self, series_id: int, series: SeriesUpdate) -> SeriesPublic:
        with Session.begin() as session:
            row = Series.update(
                session, series_id, **series.model_dump(exclude_unset=True)
            )
            if not row:
                raise NotFoundError("Series not found")
            _both_scores(row)
            public = SeriesPublic.from_series(row)
            derived.fill_series(session, [public])
            return public

    def delete(self, series_id: int) -> None:
        with Session.begin() as session:
            Series.delete(session, series_id)

    def get(self, series_id: int) -> SeriesPublic:
        with Session.begin() as session:
            series = session.scalars(
                select(Series)
                .options(*Series._eager_options())
                .where(col(Series.id) == series_id)
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
        filter = QueryUtil.convert_query_to_db_filter(Series, query)
        if filter is None:
            return []
        with Session.begin() as session:
            statement = (
                select(Series).options(*Series._list_eager_options()).where(filter)
            )
            if sort == "week":
                statement = statement.join(Match, col(Match.id) == Series.match_id)
            # Offset paging is deterministic only with a fixed order
            statement = (
                ordered(statement, SERIES_SORTS, sort, order, col(Series.id))
                .offset(offset)
                .limit(limit)
            )
            series_list = session.scalars(statement).all()
            result = [SeriesPublic.from_series_reduced(s) for s in series_list]
            derived.fill_series(session, result)
            return result

    def count(self, query: QueryElement | None, season_id: int | None = None) -> int:
        """The number of series that match the query, in one season or in all."""
        with Session.begin() as session:
            filter = QueryUtil.convert_query_to_db_filter(Series, query)
            if filter is None and season_id is None:
                return 0
            statement = select(func.count()).select_from(Series)
            if season_id is not None:
                statement = statement.where(
                    col(Series.match).has(col(Match.season_id) == season_id)
                )
            if filter is not None:
                statement = statement.where(filter)
            return session.scalar(statement) or 0

    def fantasy_series_by_week(
        self, season_id: int
    ) -> dict[int | None, list[fantasy.Series]]:
        """Every series of the season, by week, in one statement."""
        with Session.begin() as session:
            return derived.fantasy_series(session, {season_id}).get(season_id, {})

    def search_for_season_and_playday(
        self,
        season_id: int,
        playday: int,
        query: QueryElement | None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[SeriesPublic]:
        with Session.begin() as session:
            filter = QueryUtil.convert_query_to_db_filter(Series, query)
            series_list = Series.search_for_season_and_playday(
                session, season_id, playday, filter, limit=limit, offset=offset
            )
            result = [SeriesPublic.from_series_reduced(s) for s in series_list]
            derived.fill_series(session, result)
            return result

    def search_for_season(
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
        with Session.begin() as session:
            filter = QueryUtil.convert_query_to_db_filter(Series, query)
            series_list = Series.search_for_season(
                session,
                season_id,
                filter,
                limit=limit,
                offset=offset,
                sort=sort,
                order=order,
            )
            result = [SeriesPublic.from_series_reduced(s) for s in series_list]
            derived.fill_series(session, result)
            return result
