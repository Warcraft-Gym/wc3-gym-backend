import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import (
    MatchServiceDep,
    RequireLogin,
    RequireMember,
    SeriesServiceDep,
    UserServiceDep,
    event_edge_cache,
    own_match,
    require_series_runner,
)
from app.core.exceptions import ApiError, NotFoundError
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
from app.models.series_summary import SeriesSummaryPublic
from app.services import casts, series_edit, series_summary, stage_engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["series"])


@router.post("/series", status_code=201, response_model=SeriesPublic)
def add_series(
    data: SeriesCreate, claims: RequireLogin, matches: MatchServiceDep
) -> SeriesPublic:
    """Publish a series in a fixture. A captain of either team adds to his
    team's fixture up to the round's series; an admin adds any."""
    own_match(claims, data.match_id, matches)
    return series_edit.add(data, admin=is_admin(claims))


@router.put("/series/{series_id}", response_model=SeriesPublic)
def update_series(
    series_id: int,
    data: SeriesUpdate,
    claims: RequireLogin,
    matches: MatchServiceDep,
    force: bool = False,
) -> SeriesPublic:
    """Update the series data of an existing series.

    A captain of either team of its fixture sends the time, the scores, the
    races played, the host and the fantasy mark; an admin sends any field.
    Clearing the score reopens the bracket below it; `force`, an admin's,
    allows the reopen when a later series already carries a result.
    """
    admin = is_admin(claims)
    if not admin:
        own_match(claims, series_edit.fixture_of(series_id), matches)
    return series_edit.edit(series_id, data, admin=admin, force=force)


@router.delete("/series/{series_id}/result", response_model=SeriesPublic)
def clear_series_result(
    series_id: int,
    claims: RequireLogin,
    users: UserServiceDep,
    force: bool = False,
) -> SeriesPublic:
    """Take back a reported result, for whoever may report it.

    The scores, the races played and the games go, and the replays stay. A
    walkover or a forfeit, and `force`, are an admin's.
    """
    admin = is_admin(claims)
    caller = None if admin else users.id_by_discord_id(str(claims["sub"]))
    return series_edit.clear_result(series_id, admin=admin, user_id=caller, force=force)


@router.put(
    "/series/{series_id}/result-kind", dependencies=[Depends(require_series_runner)]
)
def set_result_kind(
    series_id: int, data: ResultKindWrite, service: SeriesServiceDep
) -> SeriesPublic:
    """Score a series no game was played for: a walkover or a forfeit."""
    stage_engine.set_result_kind(series_id, data)
    return service.get(series_id)


@router.put("/series/{series_id}/places", dependencies=[Depends(require_series_runner)])
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


@router.delete("/series/{series_id}", status_code=204)
def delete_series(
    series_id: int,
    service: SeriesServiceDep,
    claims: RequireLogin,
    matches: MatchServiceDep,
) -> None:
    """Delete a series by its ID. A captain of either team of its fixture
    deletes it; a series of a stage or a KOTH night is an admin's."""
    if not is_admin(claims):
        own_match(claims, series_edit.fixture_of(series_id), matches)
    service.delete(series_id)


@router.get("/series/{series_id}")
def get_series(series_id: int, service: SeriesServiceDep) -> SeriesPublic:
    """Retrieve a series by its ID."""
    return service.get(series_id)


@router.get("/events/{event_id}/series", tags=["events"])
def get_series_by_event(
    event_id: int,
    service: SeriesServiceDep,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
    player_id: int | None = None,
    team_id: int | None = None,
    match_id: int | None = None,
    is_fantasy_match: bool | None = None,
) -> list[SeriesPublic]:
    """Return one page of an event's series, at most 500, optionally filtered."""
    event_edge_cache(response, event_id)
    return service.search_for_season(
        event_id,
        None,
        limit=limit,
        offset=offset,
        player_id=player_id,
        team_id=team_id,
        match_id=match_id,
        is_fantasy_match=is_fantasy_match,
    )


@router.get("/events/{event_id}/series/summary", tags=["events"])
def get_series_summary_by_event(
    event_id: int,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
    player_id: int | None = None,
    team_id: int | None = None,
    match_id: int | None = None,
    is_fantasy_match: bool | None = None,
) -> list[SeriesSummaryPublic]:
    """Return one page of an event's fixture series as list rows, at most 500.

    The filters and the order are those of GET /events/{event_id}/series; a
    stage or round series is not in this list.
    """
    event_edge_cache(response, event_id)
    return series_summary.for_event(
        event_id,
        limit=limit,
        offset=offset,
        player_id=player_id,
        team_id=team_id,
        match_id=match_id,
        is_fantasy_match=is_fantasy_match,
    )


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
