import logging

from sqlalchemy import ColumnElement

from app.core.exceptions import NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.map import Map, MapCreate, MapPublic, MapUpdate
from app.services.base import BaseService

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
                raise NotFoundError("Map not found")
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

    def search(
        self, query: QueryElement | None, limit: int | None = None, offset: int = 0
    ) -> list[MapPublic]:
        return self._where(
            QueryUtil.convertQueryToDBFilter(Map, query), limit=limit, offset=offset
        )

    def find_by_shortname(self, shortname: str) -> list[MapPublic]:
        return self._where(Map.shortname == shortname)

    def _where(
        self,
        filter: ColumnElement[bool] | None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[MapPublic]:
        with self.get_session() as session:
            maps = Map.search(session, filter, limit=limit, offset=offset)
            if not maps:
                logger.debug(f"No maps found by searchcriteria: {filter}")
                return []
            return [MapPublic.model_validate(map) for map in maps]

    def getAll(self, limit: int | None = None, offset: int = 0) -> list[MapPublic]:
        with self.get_session() as session:
            maps = Map.getAll(session, limit=limit, offset=offset)
            return [MapPublic.model_validate(map) for map in maps]

    def create_map(self, map: MapCreate) -> MapPublic:
        return self.add(map)

    def update_map(self, map_id: int, map: MapUpdate) -> MapPublic:
        return self.update(map_id, map)

    def delete_map(self, map_id: int) -> None:
        self.delete(map_id)

    def get_map(self, map_id: int) -> MapPublic:
        map_data = self.get(map_id)
        if not map_data:
            raise NotFoundError(f"Map not found by Id: {map_id}")
        return map_data
