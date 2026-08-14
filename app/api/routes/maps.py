import logging

from fastapi import APIRouter, Depends

from app.api.deps import MapServiceDep, require_admin
from app.models.map import MapCreate, MapPublic, MapUpdate
from app.utils.query_util import QueryUtil

logger = logging.getLogger(__name__)

router = APIRouter(tags=["maps"])


@router.post(
    "/maps",
    status_code=201,
    response_model=MapPublic,
    dependencies=[Depends(require_admin)],
)
def add_map(data: MapCreate, service: MapServiceDep):
    """Create a new map with the provided details."""
    return service.create_map(data)


@router.put(
    "/maps/{map_id}", response_model=MapPublic, dependencies=[Depends(require_admin)]
)
def update_map(map_id: int, data: MapUpdate, service: MapServiceDep):
    """Update the details of an existing map."""
    return service.update_map(map_id, data)


@router.delete("/maps/{map_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_map(map_id: int, service: MapServiceDep):
    """Delete a map by their ID."""
    service.delete_map(map_id)


@router.get("/maps/{map_id}", response_model=MapPublic)
def get_map(map_id: int, service: MapServiceDep):
    """Retrieve a map by their ID."""
    return service.get_map(map_id)


@router.get("/maps", response_model=list[MapPublic])
def get_all_maps(service: MapServiceDep):
    """Retrieve all maps."""
    return service.getAll()


@router.post("/maps/search", response_model=list[MapPublic])
def search_maps(service: MapServiceDep, query: str = ""):
    """Search maps by criteria using a custom query format."""
    query_param = query
    query = QueryUtil.parseQuery(query_param)
    if not query or not query.elementA:
        raise Exception(f"No valid query found: {query_param}")
    return service.search(query)
