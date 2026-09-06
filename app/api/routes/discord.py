"""The interactions endpoint behind the Discord adapter."""

import json

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from app.api.deps import (
    FantasyTeamServiceDep,
    LadderServiceDep,
    SeasonServiceDep,
    SeriesServiceDep,
    UserServiceDep,
)
from app.core.exceptions import ApiError
from app.services import interactions

router = APIRouter(tags=["discord"])


@router.post("/discord/interactions", response_model=None)
async def discord_interaction(
    request: Request,
    series_service: SeriesServiceDep,
    user_service: UserServiceDep,
    ladder_service: LadderServiceDep,
    season_service: SeasonServiceDep,
    fantasy_service: FantasyTeamServiceDep,
) -> dict:
    """One interaction, forwarded by the adapter with Discord's signature headers.

    The signature is the whole auth: no Clerk session, no admin token. A bad
    or missing signature answers 401 and nothing is read.
    """
    body = await request.body()
    if not interactions.verified(request.headers, body):
        raise ApiError(401, {"error": "bad signature"})
    services = interactions.Services(
        series_service, user_service, ladder_service, season_service, fantasy_service
    )
    return await run_in_threadpool(interactions.handle, json.loads(body), services)
