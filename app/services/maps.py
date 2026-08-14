import logging

from app.exceptions import NotFoundException
from app.models.map import Map, MapCreate, MapPublic, MapUpdate
from app.services.base import BaseService
from app.utils.query_util import QueryElement, QueryUtil

logger = logging.getLogger(__name__)


class MapService(BaseService):
    def add(self, map: MapCreate) -> MapPublic:
        with self.get_session() as session:
            new_map = Map.add(session, map.model_dump())
            return MapPublic.model_validate(new_map)

    def update(self, map_id: int, map: MapUpdate) -> MapPublic:
        with self.get_session() as session:
            updated = Map.update(session, map_id, **map.model_dump())
            if not updated:
                raise NotFoundException("Map not found")
            return MapPublic.model_validate(updated)

    def delete(self, map_id: int) -> None:
        with self.get_session() as session:
            Map.delete(session, map_id)

    def get(self, map_id: int) -> MapPublic | None:
        with self.get_session() as session:
            map = Map.getById(session, map_id)
            if not map:
                return None
            return MapPublic.model_validate(map)

    def search(self, query: QueryElement | None) -> list[MapPublic]:
        with self.get_session() as session:
            filter = QueryUtil.convertQueryToDBFilter(Map, query)
            maps = Map.search(session, filter)
            if not maps:
                logger.debug(f"No maps found by searchcriteria: {query}")
                return []
            return [MapPublic.model_validate(map) for map in maps]

    def getAll(self) -> list[MapPublic]:
        with self.get_session() as session:
            return [MapPublic.model_validate(map) for map in Map.getAll(session)]

    def create_map(self, map: MapCreate) -> MapPublic:
        return self.add(map)

    def update_map(self, map_id: int, map: MapUpdate) -> MapPublic:
        return self.update(map_id, map)

    def delete_map(self, map_id: int) -> None:
        self.delete(map_id)

    def get_map(self, map_id: int) -> MapPublic:
        map_data = self.get(map_id)
        if not map_data:
            raise NotFoundException(f"Map not found by Id: {map_id}")
        return map_data
