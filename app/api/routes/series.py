import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    RequireLogin,
    RequireMember,
    SeriesServiceDep,
    UserServiceDep,
    require_admin,
)
from app.api.search import SearchQuery
from app.core.exceptions import ApiError, NotFoundError
from app.core.query import QueryUtil
from app.core.security import is_admin
from app.models.series import (
    ResultKindWrite,
    SeriesCreate,
    SeriesPublic,
    SeriesUpdate,
    StageSeriesRow,
)
from app.models.series_cast import CastPublic, CastWrite, ClaimWrite, VodWrite
from app.models.series_side import LobbySidesWrite, PlacesWrite
from app.services import casts, stage_engine

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
    return service.add(data)


@router.put(
    "/series/{series_id}",
    response_model=SeriesPublic,
    dependencies=[Depends(require_admin)],
)
def update_series(
    series_id: int,
    data: SeriesUpdate,
    service: SeriesServiceDep,
    force: bool = False,
) -> SeriesPublic:
    """Update the series data of an existing series.

    Clearing the score reopens the bracket below it; `force` allows the reopen
    when a later series already carries a result.
    """
    return service.update(series_id, data, force)


@router.put("/series/{series_id}/result-kind", dependencies=[Depends(require_admin)])
def set_result_kind(series_id: int, data: ResultKindWrite) -> SeriesPublic:
    """Score a series no game was played for: a walkover or a forfeit."""
    return stage_engine.set_result_kind(series_id, data)


@router.put("/series/{series_id}/places", dependencies=[Depends(require_admin)])
def set_places(series_id: int, data: PlacesWrite) -> StageSeriesRow:
    """Enter where every side of a free for all lobby finished.

    A lobby plays one game, so the places settle it, and a round whose every
    lobby carries places seats the lobbies of the round after it.
    """
    return stage_engine.set_places(series_id, data)


@router.put("/series/{series_id}/sides")
def set_sides(
    series_id: int,
    data: LobbySidesWrite,
    claims: RequireLogin,
    users: UserServiceDep,
) -> StageSeriesRow:
    """Seat a lobby again before it is played, or name a fixture side roster.

    A body naming `sides` writes the roster each side of a fixture series
    fields, which a captain of that team writes for his own side. Seating a
    lobby again stays an admin act.
    """
    admin = is_admin(claims)
    if not admin and not data.sides:
        raise ApiError(403, {"error": "Admins only"})
    caller = None if admin else users.id_by_discord_id(str(claims["sub"]))
    return stage_engine.set_sides(series_id, data, admin=admin, user_id=caller)


@router.delete(
    "/series/{series_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_series(series_id: int, service: SeriesServiceDep) -> None:
    """Delete a series by its ID."""
    service.delete(series_id)


@router.get("/series/{series_id}")
def get_series(series_id: int, service: SeriesServiceDep) -> SeriesPublic:
    """Retrieve a series by its ID."""
    return service.get(series_id)


@router.post("/series/search")
def search_series(
    service: SeriesServiceDep,
    query: SearchQuery,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SeriesPublic]:
    """Search series by criteria using a custom query format."""
    return service.search(query, limit=limit, offset=offset)


@router.post("/events/{event_id}/rounds/{playday}/series/search", tags=["events"])
@router.post("/series/season/{event_id}/playday/{playday}/search", deprecated=True)
def search_series_by_event_and_playday(
    event_id: int,
    playday: int,
    service: SeriesServiceDep,
    query: str = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SeriesPublic]:
    """Return series matching the search query for one event round."""
    parsed_query = QueryUtil.parse_query(query)
    return service.search_for_season_and_playday(
        event_id, playday, parsed_query, limit=limit, offset=offset
    )


@router.get("/events/{event_id}/series", tags=["events"])
@router.get("/series/season/{event_id}", deprecated=True)
def get_series_by_event(
    event_id: int,
    service: SeriesServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SeriesPublic]:
    """Return one page of an event's series, at most 500."""
    return service.search_for_season(event_id, None, limit=limit, offset=offset)


@router.post("/events/{event_id}/series/search", tags=["events"])
@router.post("/series/season/{event_id}/search", deprecated=True)
def search_series_by_event(
    event_id: int,
    service: SeriesServiceDep,
    query: str = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SeriesPublic]:
    """Return series matching the search query for an event."""
    parsed_query = QueryUtil.parse_query(query)
    return service.search_for_season(event_id, parsed_query, limit=limit, offset=offset)


def caster(claims: RequireMember, user_service: UserServiceDep) -> tuple[int, bool]:
    """The users row behind a member's session, and whether it is an admin."""
    user_id = user_service.id_by_discord_id(str(claims["sub"]))
    if user_id is None:
        raise NotFoundError("player_not_found")
    admin = is_admin(claims)
    return user_id, admin


Caster = Annotated[tuple[int, bool], Depends(caster)]


@router.get("/series/{series_id}/casts")
def get_casts(series_id: int) -> list[CastPublic]:
    """Who casts this series, on which channel."""
    return casts.for_series(series_id)


@router.post("/series/{series_id}/casts", status_code=201)
def claim_series(series_id: int, data: ClaimWrite, who: Caster) -> list[CastPublic]:
    """Claim the series to cast it. A series that is over is claimed with its VOD."""
    return casts.claim(series_id, who[0], data.channel_url, data.vod_url)


@router.put("/series/{series_id}/casts/{cast_id}")
def update_cast(
    series_id: int, cast_id: int, data: CastWrite, who: Caster
) -> list[CastPublic]:
    """Change the channel of your own cast; an admin changes any."""
    return casts.update(series_id, cast_id, *who, data.channel_url)


@router.put("/series/{series_id}/casts/{cast_id}/vod")
def set_cast_vod(
    series_id: int, cast_id: int, data: VodWrite, who: Caster
) -> list[CastPublic]:
    """Paste or clear the VOD of your own cast; an admin does it for any."""
    return casts.set_vod(series_id, cast_id, *who, data.vod_url)


@router.delete("/series/{series_id}/casts/{cast_id}", status_code=204)
def unclaim_series(series_id: int, cast_id: int, who: Caster) -> None:
    """Remove your own cast; an admin removes any."""
    casts.unclaim(series_id, cast_id, *who)


@router.get("/casts/last")
def last_cast_channel(who: Caster) -> dict[str, str | None]:
    """The channel of your newest claim, to pre-fill the next one."""
    return {"channel_url": casts.last_channel(who[0])}
