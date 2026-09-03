import os
from datetime import timedelta

from fastapi import APIRouter
from sqlmodel import col, select

from app.api.deps import Credentials, LadderServiceDep
from app.core.db import Session
from app.core.exceptions import ApiError
from app.models.relationships import DBUserSeasonSignup
from app.models.season import Season
from app.models.types import utcnow
from app.models.user import User, UserReduced
from app.models.w3c_stats import W3CSyncResult
from app.services.users import W3C_SYNC_WORKERS

router = APIRouter(tags=["jobs"])


@router.get("/jobs/w3c-sync")
def sync_w3c_cron(credentials: Credentials, service: LadderServiceDep) -> W3CSyncResult:
    """One wave of the stalest signups of the season running today, for Vercel Cron.

    Bearer auth against CRON_SECRET; unset answers 503, so the route is never
    a public trigger. Off-season answers empty and makes no W3C call.
    """
    secret = os.getenv("CRON_SECRET")
    if not secret:
        raise ApiError(503, {"error": "CRON_SECRET is not set"})
    if credentials is None or credentials.credentials != secret:
        raise ApiError(401, {"error": "Unauthorized"})

    today = utcnow().date()
    with Session() as session:
        season_id = session.scalar(
            select(col(Season.id)).where(
                Season.start_date <= today, Season.end_date >= today
            )
        )
        if season_id is None:
            return W3CSyncResult()
        rows = session.execute(
            select(col(User.id), col(User.name), col(User.battleTag))
            .join(DBUserSeasonSignup, col(DBUserSeasonSignup.user_id) == User.id)
            .where(col(DBUserSeasonSignup.season_id) == season_id)
            .order_by(col(User.ladder_synced_at).asc().nulls_first())
            .limit(W3C_SYNC_WORKERS)
        ).all()

    users = [UserReduced(id=r.id, name=r.name, battleTag=r.battleTag) for r in rows]
    return service.sync_season_users(season_id, users, timedelta(0))
