import logging
from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBSeries import DBSeries
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload
from custom_exceptions import DBException
from src.util.query_util import QueryUtil
from src.dtos.series_dto import SeriesDTO

logger = logging.getLogger(__name__)

class SeriesDBService(AbstractDatabaseService):
    def add(self, series: SeriesDTO):
        try:
            session = self.Session()
            series = DBSeries.add(session, series.to_db_dict())
            if not series:
                raise DBException("Series could not be created!")
            return SeriesDTO.from_dbseries(series)
        except SQLAlchemyError as e:
            raise DBException(f"Database error: {e}")
        finally:
            session.close()
    
    def update(self, series: SeriesDTO):
        try:
            session = self.Session()
            series = DBSeries.update(session, series.id, **series.to_db_dict())
            if not series:
                raise DBException("Series could not be updated!")
            return SeriesDTO.from_dbseries(series)
        except SQLAlchemyError as e:
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def delete(self, series_id):
        try:
            session = self.Session()
            DBSeries.delete(session, series_id)
        except SQLAlchemyError as e:
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def get(self, series_id):
        try:
            from src.database.model.DBUser import DBUser
            from src.database.model.DBRelationships import DBUserTeamSeason
            session = self.Session()
            # Eager load relationships to avoid N+1 queries, load w3c_stats and team_seasons with season for players
            series = session.query(DBSeries)\
                .options(
                    joinedload(DBSeries.match).noload('*'),
                    joinedload(DBSeries.player1).joinedload(DBUser.w3c_stats),
                    joinedload(DBSeries.player1).joinedload(DBUser.team_seasons).joinedload(DBUserTeamSeason.season),
                    joinedload(DBSeries.player2).joinedload(DBUser.w3c_stats),
                    joinedload(DBSeries.player2).joinedload(DBUser.team_seasons).joinedload(DBUserTeamSeason.season)
                )\
                .filter_by(id=series_id).first()
            if not series:
                raise DBException("Series could not be found")
            return SeriesDTO.from_dbseries(series)
        except SQLAlchemyError as e:
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def getAll(self):
        try:
            from src.database.model.DBUser import DBUser
            from src.database.model.DBRelationships import DBUserTeamSeason
            result = []
            session = self.Session()
            # Eager load relationships, load w3c_stats and team_seasons with season for players
            series = session.query(DBSeries)\
                .options(
                    joinedload(DBSeries.match).noload('*'),
                    joinedload(DBSeries.player1).joinedload(DBUser.w3c_stats),
                    joinedload(DBSeries.player1).joinedload(DBUser.team_seasons).joinedload(DBUserTeamSeason.season),
                    joinedload(DBSeries.player2).joinedload(DBUser.w3c_stats),
                    joinedload(DBSeries.player2).joinedload(DBUser.team_seasons).joinedload(DBUserTeamSeason.season)
                ).all()
            for single_series in series:
                result.append(SeriesDTO.from_dbseries(single_series))
            return result
        except SQLAlchemyError as e:
                raise DBException(f"Database error: {e}")

    def search(self, query):
        with self.get_session() as session:
            try:
                from src.database.model.DBUser import DBUser
                from src.database.model.DBRelationships import DBUserTeamSeason
                result = []
                filter = QueryUtil.convertQueryToDBFilter(DBSeries, query)
                # Eager load related entities, load w3c_stats and team_seasons with season for players
                series_list = session.query(DBSeries)\
                    .options(
                        joinedload(DBSeries.match).noload('*'),
                        joinedload(DBSeries.player1).joinedload(DBUser.w3c_stats),
                        joinedload(DBSeries.player1).joinedload(DBUser.team_seasons).joinedload(DBUserTeamSeason.season),
                        joinedload(DBSeries.player2).joinedload(DBUser.w3c_stats),
                        joinedload(DBSeries.player2).joinedload(DBUser.team_seasons).joinedload(DBUserTeamSeason.season)
                    )\
                    .filter(filter).all() if filter is not None else []
                if not series_list:
                    logger.debug(f"No series found by searchcriteria: {query}")
                    return result
                for series in series_list:
                    result.append(SeriesDTO.from_dbseries(series))
                return result
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")
            
    def searchForSeasonAndPlayday(self, season_id, playday, query):
        with self.get_session() as session:
            try:
                result = []
                filter = QueryUtil.convertQueryToDBFilter(DBSeries, query)
                series_list = DBSeries.searchForSeasonAndPlayday(session, season_id, playday, filter)
                if not series_list:
                    logger.debug(f"No series found by searchcriteria: {query}")
                    return result
                for series in series_list:
                    result.append(SeriesDTO.from_dbseries(series))
                return result
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")
            
    def searchForSeason(self, season_id, query):
        with self.get_session() as session:
            try:
                result = []
                filter = QueryUtil.convertQueryToDBFilter(DBSeries, query)
                series_list = DBSeries.searchForSeason(session, season_id, filter)
                if not series_list:
                    logger.debug(f"No series found by searchcriteria: {query}")
                    return result
                for series in series_list:
                    result.append(SeriesDTO.from_dbseries(series))
                return result
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")