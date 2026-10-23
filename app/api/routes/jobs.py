import logging
import os
from datetime import timedelta
from time import monotonic
from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.deps import Credentials, LadderServiceDep
from app.core.exceptions import ApiError
from app.models.egress_ledger import EgressLedger
from app.models.egress_snapshot import EgressSnapshotResult, EgressWindow
from app.models.types import utcnow
from app.models.w3c_stats import W3CSyncResult
from app.services import (
    casts,
    cup_announcements,
    discord_posts,
    egress,
    egress_monitor,
    egress_snapshot,
)
from app.services.users import stalest_members

log = logging.getLogger(__name__)

router = APIRouter(tags=["jobs"])

# The route drains waves this long, under the 60 s Vercel function limit
DRAIN_SECONDS = 50

# The longest the cast-reminders Worker sleeps between calls: a series claimed
# meanwhile, or a cup moved, is seen within this
MAX_SLEEP = timedelta(minutes=30)


def only_the_scheduler(credentials: Credentials, key: str = "CRON_SECRET") -> None:
    """Bearer auth against the secret named `key`; unset answers 503, so a /jobs
    route is never a public trigger."""
    secret = os.getenv(key)
    if not secret:
        raise ApiError(503, {"error": f"{key} is not set"})
    if credentials is None or credentials.credentials != secret:
        raise ApiError(401, {"error": "Unauthorized"})


@router.get("/jobs/cast-reminders")
def cast_reminders(credentials: Credentials) -> dict[str, int | str]:
    """Call the audience to every claimed series about to start, one card each.

    Vercel Hobby runs a cron once a day, so a Cloudflare Worker in
    wc3-gym-discord-bot (cron/) calls this every five minutes; its failures
    show in that Worker's Cron Events. A series already carrying its card is
    skipped, so a run that repeats posts nothing twice. The Worker holds its own
    secret, so a leak there triggers nothing but this job.

    The same run calls every cup, and every round of a cup played over
    rounds, that starts within the hour to check in, each once.

    `next_run` is when the next card or call can fall due, at most MAX_SLEEP
    away. The Worker skips its ticks before it, so the backend sleeps through
    the hours with nothing scheduled.
    """
    only_the_scheduler(credentials, "CLOUDFLARE_CRON_SECRET")
    now = utcnow()
    due = casts.starting_soon(now)
    posted = sum(discord_posts.post_reminder(row) for row in due)
    cup_reminders = cup_announcements.remind_due(now)
    until = now + MAX_SLEEP
    soonest = [
        at
        for at in (
            casts.next_reminder(now, until),
            cup_announcements.next_call(now, until),
        )
        if at is not None
    ]
    return {
        "posted": posted,
        "cup_reminders": cup_reminders,
        "next_run": min(soonest, default=until).isoformat(),
    }


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
        users = stalest_members(started)
        if not users:
            return result
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
