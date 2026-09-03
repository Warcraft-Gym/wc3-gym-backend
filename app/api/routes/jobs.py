import os
from datetime import timedelta
from time import monotonic

from fastapi import APIRouter
from sqlmodel import col, select

from app.api.deps import Credentials, LadderServiceDep
from app.core.db import Session
from app.core.exceptions import ApiError
from app.models.relationships import DBUserSeasonSignup
from app.models.types import utcnow
from app.models.user import User, UserReduced
from app.models.w3c_stats import W3CSyncResult
from app.services.users import W3C_SYNC_WORKERS

router = APIRouter(tags=["jobs"])

# The route drains waves this long, under the 60 s Vercel function limit
DRAIN_SECONDS = 50


@router.get("/jobs/w3c-sync")
def sync_w3c_cron(credentials: Credentials, service: LadderServiceDep) -> W3CSyncResult:
    """The stalest members, over their whole ladder history, one wave at a
    time, for Vercel Cron. A member is anyone signed up for a season. It
    stops when the time is up, when a wave comes around to players this run
    stamped, or when a wave syncs nobody.

    Bearer auth against CRON_SECRET; unset answers 503, so the route is never
    a public trigger.
    """
    secret = os.getenv("CRON_SECRET")
    if not secret:
        raise ApiError(503, {"error": "CRON_SECRET is not set"})
    if credentials is None or credentials.credentials != secret:
        raise ApiError(401, {"error": "Unauthorized"})

    started = utcnow()
    deadline = monotonic() + DRAIN_SECONDS
    result = W3CSyncResult()
    while True:
        with Session() as session:
            rows = session.execute(
                select(
                    col(User.id),
                    col(User.name),
                    col(User.battleTag),
                    col(User.ladder_synced_at),
                )
                .where(
                    col(User.id).in_(select(col(DBUserSeasonSignup.user_id)).distinct())
                )
                .order_by(col(User.ladder_synced_at).asc().nulls_first(), col(User.id))
                .limit(W3C_SYNC_WORKERS)
            ).all()
        rows = [
            r
            for r in rows
            if r.ladder_synced_at is None or r.ladder_synced_at < started
        ]
        if not rows:
            return result
        users = [UserReduced(id=r.id, name=r.name, battleTag=r.battleTag) for r in rows]
        wave = service.sync_members(users, timedelta(0))
        result.synced += wave.synced
        result.failed += wave.failed
        if not wave.synced or monotonic() >= deadline:
            return result
