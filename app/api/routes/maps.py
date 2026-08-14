import logging
from typing import Annotated

from fastapi import APIRouter, Body, Depends

from app.api.deps import MapServiceDep, require_admin
from app.schemas.map import Map
from app.utils.query_util import QueryUtil

logger = logging.getLogger(__name__)

router = APIRouter(tags=["maps"])


@router.post("/maps", status_code=201, dependencies=[Depends(require_admin)])
def add_map(data: Annotated[dict, Body()], service: MapServiceDep):
    """Create a new map with the provided details."""
    map = service.create_map(Map(data))
    return map.to_dict() if map else None


@router.put("/maps/{map_id}", dependencies=[Depends(require_admin)])
def update_map(map_id: int, data: Annotated[dict, Body()], service: MapServiceDep):
    """Update the details of an existing map."""
    map = service.update_map(map_id, Map(data))
    return map.to_dict() if map else None


@router.delete("/maps/{map_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_map(map_id: int, service: MapServiceDep):
    """Delete a map by their ID."""
    service.delete_map(map_id)


@router.get("/maps/{map_id}")
def get_map(map_id: int, service: MapServiceDep):
    """Retrieve a map by their ID."""
    map = service.get_map(map_id)
    return map.to_dict() if map else None


@router.get("/maps")
def get_all_maps(service: MapServiceDep):
    """Retrieve all maps."""
    return [map.to_dict() for map in service.getAll() or []]


@router.post("/maps/search")
def search_maps(service: MapServiceDep, query: str = ""):
    """Search maps by criteria using a custom query format."""
    query_param = query
    query = QueryUtil.parseQuery(query_param)
    if not query or not query.elementA:
        raise Exception(f"No valid query found: {query_param}")
    return [map.to_dict() for map in service.search(query) or []]
