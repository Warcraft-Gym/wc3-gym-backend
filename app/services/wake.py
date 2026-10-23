"""The time the cast-reminder Worker next calls /jobs/cast-reminders.

A commit that writes a table the due-time reads read recomputes the soonest
reminder card or cup call and posts it to the Worker's `POST /next-run`, so
the Worker sleeps until then, and at most FLOOR. The route answers the same
value from the same function. app.core.db registers the listeners.
"""

import logging
import os
from datetime import datetime, timedelta

import requests
from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState
from sqlalchemy.orm import Session as OrmSession

from app.core.db import Session
from app.models.cup_rounds import CupLeg
from app.models.discord_post import DiscordPost
from app.models.season import Season
from app.models.series import Series
from app.models.series_cast import SeriesCast
from app.models.types import utcnow
from app.services import casts, cup_announcements

log = logging.getLogger(__name__)

# The longest the Worker sleeps with nothing due
FLOOR = timedelta(hours=24)
# How long the push waits for the Worker; a request can push twice, so a dead Worker costs 4 s at most
TIMEOUT = 2
# The session.info key a write to a watched table sets
MARK = "wake"

# The models the two due-time reads read; a write to any of them pushes
WATCHED: tuple[type, ...] = (
    Series,  # casts.next_reminder: the start and the scores
    SeriesCast,  # casts.next_reminder: which series are claimed
    DiscordPost,  # casts.next_reminder, through discord_posts.reminded: the card posted
    Season,  # cup_announcements.next_call: the cup, its start and its check-in
    CupLeg,  # cup_announcements.next_call: a round's start, finish and check-in close
)

# The seam the tests replace
post = requests.post


def next_run(now: datetime) -> datetime:
    """The soonest a reminder card or a cup call falls due, at most FLOOR after `now`."""
    until = now + FLOOR
    due = (casts.next_reminder(now, until), cup_announcements.next_call(now, until))
    return min((at for at in due if at is not None), default=until)


def push(now: datetime | None = None) -> None:
    """Post the next run to the Worker; unset CLOUDFLARE_WORKER_URL posts nothing.
    A failure is logged and never raises."""
    url = os.getenv("CLOUDFLARE_WORKER_URL")
    if not url:
        return
    try:
        at = next_run(now or utcnow())
        response = post(
            f"{url.rstrip('/')}/next-run",
            json={"next_run": at.isoformat()},
            headers={
                "Authorization": f"Bearer {os.getenv('CLOUDFLARE_CRON_SECRET', '')}"
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
    except Exception as error:
        status = getattr(getattr(error, "response", None), "status_code", None)
        log.warning("next-run push failed: %s %s", type(error).__name__, status)


@event.listens_for(Session, "after_flush")
def _flushed(session: OrmSession, _: object) -> None:
    if any(
        isinstance(row, WATCHED)
        for row in (*session.new, *session.dirty, *session.deleted)
    ):
        session.info[MARK] = True


@event.listens_for(Session, "do_orm_execute")
def _executed(state: ORMExecuteState) -> None:
    """A bulk insert, update or delete names its table here, never in a flush."""
    mapper = state.bind_mapper
    if (
        (state.is_insert or state.is_update or state.is_delete)
        and mapper is not None
        and issubclass(mapper.class_, WATCHED)
    ):
        state.session.info[MARK] = True


@event.listens_for(Session, "after_commit")
def _committed(session: OrmSession) -> None:
    # a savepoint's release fires this too; the outer commit is the one that pushes
    if session.get_nested_transaction() is not None:
        return
    # ponytail: every marked commit pushes, inside the request; upgrade: a task after the response
    if session.info.pop(MARK, False):
        push()


@event.listens_for(Session, "after_rollback")
def _rolled_back(session: OrmSession) -> None:
    if session.get_nested_transaction() is None:
        session.info.pop(MARK, None)
