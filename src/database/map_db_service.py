import logging
from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBMap import DBMap
from src.dtos.map_dto import MapDTO
from sqlalchemy.exc import SQLAlchemyError
from custom_exceptions import DBException
from src.util.query_util import QueryUtil

logger = logging.getLogger(__name__)

class MapDBService(AbstractDatabaseService):
    def add(self, map : MapDTO):
        with self.get_session() as session:
            try:
                map = DBMap.add(session, map.to_dict())
                if not map:
                    raise DBException("Map could not be created!")
                return MapDTO.from_dbmap(map)              
            except SQLAlchemyError as e:
                # Log the error and handle it
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")


    def update(self, map: MapDTO):
        with self.get_session() as session:
            try:
                map = DBMap.update(session, map.id, **map.to_dict())
                if not map:
                    raise DBException("Map could not be updated")
                return MapDTO.from_dbmap(map)
            except SQLAlchemyError as e:
                # Log the error and handle it
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def delete(self, map_id):
        with self.get_session() as session:
            try:
                DBMap.delete(session, map_id)
            except SQLAlchemyError as e:
                # Log the error and handle it
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def get(self, map_id):
        with self.get_session() as session:
            try:
                map = DBMap.getById(session, map_id)
                if not map:
                    return None
                return MapDTO.from_dbmap(map)
            except SQLAlchemyError as e:
                # Log the error and handle it
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")


    def search(self, query):
        with self.get_session() as session:
            try:
                result = []
                filter = QueryUtil.convertQueryToDBFilter(DBMap, query)
                maps = DBMap.seach(session, filter)
                if not maps:
                    logger.debug(f"No maps found by searchcriteria: {query}")
                    return result
                
                for map in maps:
                    result.append(MapDTO.from_dbmap(map))
                return result
            except SQLAlchemyError as e:
                # Log the error and handle it
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def getAll(self):
        with self.get_session() as session:
            try:
                result = []
                maps = DBMap.getAll(session)
                
                for map in maps:
                    result.append(MapDTO.from_dbmap(map))
                return result
            except SQLAlchemyError as e:
                # Log the error and handle it
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")