import logging
from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBMap import DBMap
from src.schemas.map import Map
from custom_exceptions import DBException
from src.util.query_util import QueryUtil

logger = logging.getLogger(__name__)

class MapDBService(AbstractDatabaseService):
    def add(self, map : Map):
        with self.get_session() as session:
            map = DBMap.add(session, map.to_dict())
            if not map:
                raise DBException("Map could not be created!")
            return Map.from_dbmap(map)              


    def update(self, map: Map):
        with self.get_session() as session:
            map = DBMap.update(session, map.id, **map.to_dict())
            if not map:
                raise DBException("Map could not be updated")
            return Map.from_dbmap(map)

    def delete(self, map_id):
        with self.get_session() as session:
            DBMap.delete(session, map_id)

    def get(self, map_id):
        with self.get_session() as session:
            map = DBMap.getById(session, map_id)
            if not map:
                return None
            return Map.from_dbmap(map)


    def search(self, query):
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(DBMap, query)
            maps = DBMap.search(session, filter)
            if not maps:
                logger.debug(f"No maps found by searchcriteria: {query}")
                return result
                
            for map in maps:
                result.append(Map.from_dbmap(map))
            return result

    def getAll(self):
        with self.get_session() as session:
            result = []
            maps = DBMap.getAll(session)
                
            for map in maps:
                result.append(Map.from_dbmap(map))
            return result
