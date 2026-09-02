from sqlalchemy import select
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.map import Map, MapCreate, MapPublic, MapUpdate
from app.services import blob


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
        """Put the picture in the store, then point the row at it, the way a team logo is stored."""
        # at the boundary the bytes arrive at, so it holds whatever the store is or is stubbed to be
        blob.icon_type(file)
        # the store is not part of the transaction, so the put happens first: a put that is never
        # committed leaves an unreferenced blob, which is cheap, while a committed row pointing at
        # a blob that was never written is a broken image
        url = blob.put_icon(f"maps/{map_id}", file)
        with Session.begin() as session:
            # locked: two uploads for one map would otherwise read the same previous URL, and the
            # loser's blob would be left behind with nothing pointing at it
            map = session.get(Map, map_id, with_for_update=True)
            if not map:
                raise NotFoundError(f"Map not found by Id: {map_id}")
            previous = map.image
            map.image = url
        if previous and blob.ours(previous):
            blob.delete_icon(previous)

    def get_image_url(self, map_id: int) -> str | None:
        """Where the picture is published, or None for a map without one."""
        with Session.begin() as session:
            return session.scalar(select(col(Map.image)).where(col(Map.id) == map_id))

    def get_all(self, limit: int | None = None, offset: int = 0) -> list[MapPublic]:
        with Session.begin() as session:
            maps = Map.get_all(session, limit=limit, offset=offset)
            return [MapPublic.model_validate(map) for map in maps]
