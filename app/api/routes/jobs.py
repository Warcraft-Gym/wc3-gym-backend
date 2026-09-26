import logging
import os
from datetime import timedelta
from time import monotonic
from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlmodel import col, select

from app.api.deps import Credentials, LadderServiceDep
from app.core.db import Session
from app.core.exceptions import ApiError
from app.models.egress_ledger import EgressLedger
from app.models.egress_snapshot import EgressSnapshotResult, EgressWindow
from app.models.relationships import DBUserSeasonSignup
from app.models.types import utcnow
from app.models.user import User, UserReduced
from app.models.w3c_stats import W3CSyncResult
from app.services import casts, discord_posts, egress, egress_monitor, egress_snapshot
from app.services.users import W3C_SYNC_WORKERS

log = logging.getLogger(__name__)

router = APIRouter(tags=["jobs"])

# The route drains waves this long, under the 60 s Vercel function limit
DRAIN_SECONDS = 50


def only_the_scheduler(credentials: Credentials) -> None:
    """Bearer auth against CRON_SECRET; unset answers 503, so a /jobs route is
    never a public trigger."""
    secret = os.getenv("CRON_SECRET")
    if not secret:
        raise ApiError(503, {"error": "CRON_SECRET is not set"})
    if credentials is None or credentials.credentials != secret:
        raise ApiError(401, {"error": "Unauthorized"})


@router.get("/jobs/cast-reminders")
def cast_reminders(credentials: Credentials) -> dict[str, int]:
    """Call the audience to every claimed series about to start, one card each.

    Vercel Hobby runs a cron once a day, so a Cloudflare Worker in
    wc3-gym-discord-bot (cron/) calls this every five minutes; its failures
    show in that Worker's Cron Events. A series already carrying its card is
    skipped, so a run that repeats posts nothing twice.
    """
    only_the_scheduler(credentials)
    due = casts.starting_soon(utcnow())
    return {"posted": sum(discord_posts.post_reminder(row) for row in due)}


@router.get("/jobs/w3c-sync")
def sync_w3c_cron(credentials: Credentials, service: LadderServiceDep) -> W3CSyncResult:
    """The stalest members, over their stored ladder history, one wave at a
    time, for Vercel Cron. A member is anyone signed up for a season. It
    stops when the time is up, when a wave comes around to players this run
    stamped, or when a wave syncs nobody.
    """
    only_the_scheduler(credentials)

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


@router.get("/jobs/egress")
def egress_ledger(
    credentials: Credentials,
    response: Response,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> list[EgressLedger]:
    """What each route cost the database over the last `days` days, today
    included, most rows first. This route is not recorded in the ledger."""
    only_the_scheduler(credentials)
    response.headers["Cache-Control"] = "no-store"
    return egress.recent(days)


@router.get("/jobs/egress-snapshot")
def take_egress_snapshot(credentials: Credentials) -> EgressSnapshotResult:
    """Copy pg_stat_statements into egress_snapshot and diff it with the copy before,
    for Vercel Cron once a day. Without pg_stat_statements it answers available: false;
    within an hour of the last snapshot it writes nothing and answers `skipped`.
    Each run that writes posts to the DEV_ALERTS_WEBHOOK_URL channel: an alert when the level
    turns red or unavailable, a recovery when it clears, and the daily digest."""
    only_the_scheduler(credentials)
    try:
        result = egress_snapshot.take()
    except Exception as error:
        egress_monitor.crashed(type(error).__name__)
        raise
    try:
        egress_monitor.report(result)
    except Exception as error:
        # The snapshot is committed: a monitor failure is logged and the run still answers
        log.warning("egress monitor failed: %s", type(error).__name__)
    return result


@router.get("/jobs/egress-snapshots")
def egress_snapshots(
    credentials: Credentials,
    response: Response,
    days: Annotated[int, Query(ge=1, le=35)] = 7,
) -> list[EgressWindow]:
    """One window per snapshot of the last `days` days, oldest first, totals only."""
    only_the_scheduler(credentials)
    response.headers["Cache-Control"] = "no-store"
    return egress_snapshot.recent(days)
