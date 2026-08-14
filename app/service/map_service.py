from app.database.map_db_service import MapDBService
from app.exceptions import NotFoundException
from app.schemas.map import Map


class MapAppService:
    def __init__(self, map_service: MapDBService):
        self.map_service = map_service

    def create_map(self, map: Map):
        # remove id, db generates the id
        map.id = None
        map_data = self.map_service.add(map)
        return map_data

    def update_map(self, map_id, map: Map):
        map.id = map_id
        map_data = self.map_service.update(map)
        return map_data

    def delete_map(self, map_id: int):
        self.map_service.delete(map_id)

    def get_map(self, map_id: int):
        map_data = self.map_service.get(map_id)
        if not map_data:
            raise NotFoundException(f"Map not found by Id: {map_id}")
        return map_data

    def getAll(self):
        maps_data = self.map_service.getAll()
        return maps_data

    def search(self, query):
        maps_data = self.map_service.search(query)
        return maps_data
