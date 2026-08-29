import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import MapServiceDep, require_admin
from app.core.exceptions import BadRequestError
from app.core.query import QueryUtil
from app.models.map import MapCreate, MapPublic, MapUpdate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["maps"])


@router.post(
    "/maps",
    status_code=201,
    response_model=MapPublic,
    dependencies=[Depends(require_admin)],
)
def add_map(data: MapCreate, service: MapServiceDep) -> MapPublic:
    """Create a new map with the provided details."""
    return service.add(data)


@router.put(
    "/maps/{map_id}", response_model=MapPublic, dependencies=[Depends(require_admin)]
)
def update_map(map_id: int, data: MapUpdate, service: MapServiceDep) -> MapPublic:
    """Update the details of an existing map."""
    return service.update(map_id, data)


@router.delete("/maps/{map_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_map(map_id: int, service: MapServiceDep) -> None:
    """Delete a map by their ID."""
    service.delete(map_id)


@router.get("/maps/{map_id}", response_model=MapPublic)
def get_map(map_id: int, service: MapServiceDep) -> MapPublic:
    """Retrieve a map by their ID."""
    return service.get(map_id)


@router.get("/maps", response_model=list[MapPublic])
def get_all_maps(
    service: MapServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MapPublic]:
    """Retrieve one page of maps, at most 500."""
    return service.get_all(limit=limit, offset=offset)


@router.post("/maps/search", response_model=list[MapPublic])
def search_maps(
    service: MapServiceDep,
    query: str = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MapPublic]:
    """Search maps by criteria using a custom query format."""
    parsed = QueryUtil.parse_query(query)
    if not parsed or not parsed.elementA:
        raise BadRequestError(f"No valid query found: {query}")
    return service.search(parsed, limit=limit, offset=offset)
