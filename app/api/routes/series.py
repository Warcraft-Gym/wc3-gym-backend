import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import SeriesServiceDep, require_admin
from app.core.exceptions import BadRequestError
from app.core.query import QueryUtil
from app.models.series import SeriesCreate, SeriesPublic, SeriesUpdate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["series"])


@router.post(
    "/series",
    status_code=201,
    response_model=SeriesPublic,
    dependencies=[Depends(require_admin)],
)
def add_series(data: SeriesCreate, service: SeriesServiceDep) -> SeriesPublic:
    """Create a new series with the provided data"""
    return service.create_series(data)


@router.put(
    "/series/{series_id}",
    response_model=SeriesPublic,
    dependencies=[Depends(require_admin)],
)
def update_series(
    series_id: int, data: SeriesUpdate, service: SeriesServiceDep
) -> SeriesPublic:
    """Update the series data of an existing series"""
    return service.update_series(series_id, data)


@router.delete(
    "/series/{series_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_series(series_id: int, service: SeriesServiceDep) -> None:
    """Delete a series by its ID."""
    service.delete_series(series_id)


@router.get("/series/{series_id}")
def get_series(series_id: int, service: SeriesServiceDep) -> SeriesPublic:
    """Retrieve a series by its ID."""
    return service.get(series_id)


@router.post("/series/search")
def search_series(
    service: SeriesServiceDep,
    query: str = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SeriesPublic]:
    """Search series by criteria using a custom query format."""
    parsed_query = QueryUtil.parseQuery(query)
    if not parsed_query or not parsed_query.elementA:
        raise BadRequestError(f"No valid query found: {query}")
    return service.search(parsed_query, limit=limit, offset=offset) or []


@router.post("/series/season/{season_id}/playday/{playday}/search")
def search_series_by_season_and_playday(
    season_id: int,
    playday: int,
    service: SeriesServiceDep,
    query: str = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SeriesPublic]:
    """Return series matching the search query for a specific season and a specific playday"""
    parsed_query = QueryUtil.parseQuery(query)
    return (
        service.searchForSeasonAndPlayday(
            season_id, playday, parsed_query, limit=limit, offset=offset
        )
        or []
    )


@router.get("/series/season/{season_id}")
def get_series_by_season(
    season_id: int,
    service: SeriesServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SeriesPublic]:
    """Return one page of the series of a season, at most 500."""
    return service.searchForSeason(season_id, None, limit=limit, offset=offset) or []


@router.post("/series/season/{season_id}/search")
def search_series_by_season(
    season_id: int,
    service: SeriesServiceDep,
    query: str = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SeriesPublic]:
    """Return series matching the search query for a specific season"""
    parsed_query = QueryUtil.parseQuery(query)
    return (
        service.searchForSeason(season_id, parsed_query, limit=limit, offset=offset)
        or []
    )
