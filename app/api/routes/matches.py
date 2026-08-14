import logging
from typing import Annotated

from fastapi import APIRouter, Body, Depends

from app.api.deps import MatchServiceDep, require_admin
from app.schemas.match import Match
from app.utils.query_util import QueryUtil

logger = logging.getLogger(__name__)

router = APIRouter(tags=["matches"])


@router.post("/matches", status_code=201, dependencies=[Depends(require_admin)])
def add_match(data: Annotated[dict, Body()], service: MatchServiceDep):
    """Creates a new match between two teams with the given teams and score."""
    match = service.create_match(Match(data))
    return match.to_dict() if match else None


@router.put("/matches/{match_id}", dependencies=[Depends(require_admin)])
def update_match(
    match_id: int, data: Annotated[dict, Body()], service: MatchServiceDep
):
    """Update the data of an existing matcht."""
    match = service.update_match(match_id, Match(data))
    return match.to_dict() if match else None


@router.delete(
    "/matches/{match_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_match(match_id: int, service: MatchServiceDep):
    """Delete a match by its ID."""
    service.delete_match(match_id)


@router.get("/matches/{match_id}")
def get_match(match_id: int, service: MatchServiceDep):
    """Retrieve a match by its ID."""
    match = service.get_match(match_id)
    return match.to_dict() if match else None


@router.post("/matches/search")
def search_match(service: MatchServiceDep, query: str = ""):
    """Search matches by criteria using a custom query format."""
    parsed_query = QueryUtil.parseQuery(query)
    if not parsed_query or not parsed_query.elementA:
        raise Exception(f"No valid query found: {query}")
    return [match.to_dict() for match in service.search(parsed_query) or []]
