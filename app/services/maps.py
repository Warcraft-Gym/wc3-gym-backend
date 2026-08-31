from app.core.db import Session
from app.core.exceptions import NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.map import Map, MapCreate, MapPublic, MapUpdate


class MapService:
    def add(self, map: MapCreate) -> MapPublic:
        with Session.begin() as session:
            new_map = Map.add(session, map.model_dump())
            return MapPublic.model_validate(new_map)

    def update(self, map_id: int, map: MapUpdate) -> MapPublic:
        with Session.begin() as session:
            updated = Map.update(session, map_id, **map.model_dump(exclude_unset=True))
            if not updated:
                raise NotFoundError("Map not found")
            return MapPublic.model_validate(updated)

    def delete(self, map_id: int) -> None:
        with Session.begin() as session:
            Map.delete(session, map_id)

    def get(self, map_id: int) -> MapPublic:
        with Session.begin() as session:
            map = Map.get_by_id(session, map_id)
            if not map:
                raise NotFoundError(f"Map not found by Id: {map_id}")
            return MapPublic.model_validate(map)

    def search(
        self, query: QueryElement | None, limit: int | None = None, offset: int = 0
    ) -> list[MapPublic]:
        with Session.begin() as session:
            maps = Map.search(
                session,
                QueryUtil.convert_query_to_db_filter(Map, query),
                limit=limit,
                offset=offset,
            )
            return [MapPublic.model_validate(map) for map in maps]

    def update_icon(self, map_id: int, file: bytes) -> None:
        with Session.begin() as session:
            if not Map.update(session, map_id, icon=file):
                raise NotFoundError(f"Map not found by Id: {map_id}")

    def get_icon(self, map_id: int) -> bytes | None:
        with Session.begin() as session:
            map = Map.get_by_id(session, map_id)
            if not map:
                raise NotFoundError(f"Map not found by Id: {map_id}")
            return map.icon

    def get_all(self, limit: int | None = None, offset: int = 0) -> list[MapPublic]:
        with Session.begin() as session:
            maps = Map.get_all(session, limit=limit, offset=offset)
            return [MapPublic.model_validate(map) for map in maps]
