import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    DraftSeriesServiceDep,
    MatchServiceDep,
    SeriesServiceDep,
    require_admin,
    require_captain,
)
from app.core.exceptions import ApiError
from app.models.draft_series import (
    DraftSeriesCreate,
    DraftSeriesPublic,
    DraftSeriesUpdate,
)
from app.models.series import SeriesPublic
from app.services.matches import MatchService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["draft-series"])

RequireCaptain = Annotated[dict[str, Any], Depends(require_captain)]


def _own_match(
    claims: dict[str, Any], match_id: int | None, matches: MatchService
) -> None:
    """A captain drafts the matches their team plays; an admin drafts any."""
    if claims.get("role") == "admin" or claims["sub"] == "admin":
        return
    match = matches.get(match_id) if match_id is not None else None
    if match is None or claims.get("team_id") not in (match.team1_id, match.team2_id):
        raise ApiError(403, {"error": "Your team does not play this match"})


@router.post(
    "/draft-series",
    status_code=201,
    response_model=DraftSeriesPublic,
)
def add_draft_series(
    data: DraftSeriesCreate,
    service: DraftSeriesServiceDep,
    matches: MatchServiceDep,
    claims: RequireCaptain,
) -> DraftSeriesPublic:
    """Create a new draft series for a match the caller's team plays."""
    _own_match(claims, data.match_id, matches)
    return service.add(data)


@router.put(
    "/draft-series/{draft_series_id}",
    response_model=DraftSeriesPublic,
)
def update_draft_series(
    draft_series_id: int,
    data: DraftSeriesUpdate,
    service: DraftSeriesServiceDep,
    matches: MatchServiceDep,
    claims: RequireCaptain,
) -> DraftSeriesPublic:
    """Update a draft series of a match the caller's team plays."""
    existing = service.get(draft_series_id)
    _own_match(claims, existing.match_id, matches)
    if data.match_id is not None and data.match_id != existing.match_id:
        _own_match(claims, data.match_id, matches)
    return service.update(draft_series_id, data)


@router.delete(
    "/draft-series/{draft_series_id}",
    status_code=204,
)
def delete_draft_series(
    draft_series_id: int,
    service: DraftSeriesServiceDep,
    matches: MatchServiceDep,
    claims: RequireCaptain,
) -> None:
    """Delete a draft series of a match the caller's team plays."""
    _own_match(claims, service.get(draft_series_id).match_id, matches)
    service.delete(draft_series_id)


@router.get("/draft-series/{draft_series_id}", dependencies=[Depends(require_captain)])
def get_draft_series(
    draft_series_id: int, service: DraftSeriesServiceDep
) -> DraftSeriesPublic:
    """Retrieve a draft series by its ID."""
    return service.get(draft_series_id)


@router.get("/draft-series/match/{match_id}", dependencies=[Depends(require_captain)])
def get_draft_series_by_match(
    match_id: int,
    service: DraftSeriesServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DraftSeriesPublic]:
    """Return one page of the draft series of a match, at most 500."""
    return service.get_by_match_id(match_id, limit=limit, offset=offset)


@router.delete(
    "/draft-series/match/{match_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
def delete_all_draft_series_for_match(
    match_id: int, service: DraftSeriesServiceDep
) -> None:
    """Delete all draft series for a specific match"""
    service.delete_by_match_id(match_id)


@router.post(
    "/draft-series/{draft_series_id}/promote",
    status_code=201,
    dependencies=[Depends(require_admin)],
)
def promote_draft_series(
    draft_series_id: int,
    service: DraftSeriesServiceDep,
    series_service: SeriesServiceDep,
) -> SeriesPublic:
    """Convert a draft series to a real published series and delete the draft"""
    series_create = service.convert_to_series(draft_series_id)

    # Create as real series (this will trigger all calculations)
    created_series = series_service.add(series_create)

    # Delete the draft
    service.delete(draft_series_id)

    return created_series
