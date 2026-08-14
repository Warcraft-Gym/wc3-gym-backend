import logging
from typing import Annotated

from fastapi import APIRouter, Body, Depends

from app.api.deps import SeriesServiceDep, require_admin
from app.schemas.series import Series
from app.utils.query_util import QueryUtil

logger = logging.getLogger(__name__)

router = APIRouter(tags=["series"])


@router.post("/series", status_code=201, dependencies=[Depends(require_admin)])
def add_series(data: Annotated[dict, Body()], service: SeriesServiceDep):
    """Create a new series with the provided data"""
    series = service.create_series(Series(data))
    return series.to_dict() if series else None


@router.put("/series/{series_id}", dependencies=[Depends(require_admin)])
def update_series(
    series_id: int, data: Annotated[dict, Body()], service: SeriesServiceDep
):
    """Update the series data of an existing series"""
    series = service.update_series(series_id, Series(data))
    return series.to_dict() if series else None


@router.delete(
    "/series/{series_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_series(series_id: int, service: SeriesServiceDep):
    """Delete a series by its ID."""
    service.delete_series(series_id)


@router.get("/series/{series_id}")
def get_series(series_id: int, service: SeriesServiceDep):
    """Retrieve a series by its ID."""
    series = service.get_series(series_id)
    return series.to_dict() if series else None


@router.post("/series/search")
def search_series(service: SeriesServiceDep, query: str = ""):
    """Search series by criteria using a custom query format."""
    parsed_query = QueryUtil.parseQuery(query)
    if not parsed_query or not parsed_query.elementA:
        raise Exception(f"No valid query found: {query}")
    return [series.to_dict() for series in service.search(parsed_query) or []]


@router.post("/series/season/{season_id}/playday/{playday}/search")
def search_series_by_season_and_playday(
    season_id: int, playday: int, service: SeriesServiceDep, query: str = ""
):
    """Return series matching the search query for a specific season and a specific playday"""
    parsed_query = QueryUtil.parseQuery(query)
    return [
        series.to_dict()
        for series in service.searchForSeasonAndPlayday(
            season_id, playday, parsed_query
        )
        or []
    ]


@router.get("/series/season/{season_id}")
def get_series_by_season(season_id: int, service: SeriesServiceDep):
    """Return all series for a specific season"""
    return [
        series.to_dict() for series in service.searchForSeason(season_id, None) or []
    ]


@router.post("/series/season/{season_id}/search")
def search_series_by_season(season_id: int, service: SeriesServiceDep, query: str = ""):
    """Return series matching the search query for a specific season"""
    parsed_query = QueryUtil.parseQuery(query)
    return [
        series.to_dict()
        for series in service.searchForSeason(season_id, parsed_query) or []
    ]
