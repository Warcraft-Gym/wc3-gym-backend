import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import MatchServiceDep, require_admin
from app.core.exceptions import BadRequestError
from app.core.query import QueryUtil
from app.models.match import MatchCreate, MatchPublic, MatchUpdate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["matches"])


@router.post(
    "/matches",
    status_code=201,
    response_model=MatchPublic,
    dependencies=[Depends(require_admin)],
)
def add_match(data: MatchCreate, service: MatchServiceDep) -> MatchPublic:
    """Creates a new match between two teams with the given teams and score."""
    return service.create_match(data)


@router.put(
    "/matches/{match_id}",
    response_model=MatchPublic,
    dependencies=[Depends(require_admin)],
)
def update_match(
    match_id: int, data: MatchUpdate, service: MatchServiceDep
) -> MatchPublic:
    """Update the data of an existing matcht."""
    return service.update_match(match_id, data)


@router.delete(
    "/matches/{match_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_match(match_id: int, service: MatchServiceDep) -> None:
    """Delete a match by its ID."""
    service.delete_match(match_id)


@router.get("/matches/{match_id}")
def get_match(match_id: int, service: MatchServiceDep) -> MatchPublic:
    """Retrieve a match by its ID."""
    return service.get_match(match_id)


@router.post("/matches/search")
def search_match(
    service: MatchServiceDep,
    query: str = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MatchPublic]:
    """Search matches by criteria using a custom query format."""
    parsed_query = QueryUtil.parseQuery(query)
    if not parsed_query or not parsed_query.elementA:
        raise BadRequestError(f"No valid query found: {query}")
    return service.search(parsed_query, limit=limit, offset=offset) or []
