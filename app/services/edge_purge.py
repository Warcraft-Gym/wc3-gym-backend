"""A write clears the edge copies of the reads it changes.

Each edge-cached read names its cache tags in the Vercel-Cache-Tag header:
`event-{id}` on the reads of one event, and one tag per global list
(`home`, `career`, `ladder`). A session listener maps every flushed row to
the tags it feeds, keeps them on the session until the commit, and hands
them to the request; the middleware in app/main.py asks Vercel to delete
them once the response is sent. A rollback drops them. Outside a request,
in a command or a script, the call goes out at the commit.

With VERCEL_CACHE_TOKEN unset the module sends nothing, and a failed call
is logged and ignored: the copy then lives out its s-maxage.
app.core.db registers the listener.
"""

import logging
import os
from collections.abc import Iterable
from contextvars import ContextVar
from functools import cache

import requests
from sqlalchemy import event, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.models.ladder_sync import LadderSync
from app.models.match import Match
from app.models.player_career_stats import PlayerCareerStats
from app.models.relationships import (
    DBEventRound,
    DBTeamSeasonCaptain,
    DBUserSeasonSignup,
)
from app.models.season import Season
from app.models.series import Series
from app.models.series_cast import SeriesCast
from app.models.series_game import DBSeriesGame
from app.models.series_replay import DBSeriesReplay
from app.models.series_side import SeriesSide
from app.models.series_veto_step import DBSeriesVetoStep
from app.models.team import Team
from app.models.team_season import DBTeamSeason
from app.models.user_team_season import DBUserTeamSeason
from app.models.w3c_ladder_match import W3CLadderMatch

logger = logging.getLogger(__name__)

# Delete, not invalidate: an invalidated copy is served once more while it refills
API_URL = "https://api.vercel.com/v1/edge-cache/dangerously-delete-by-tags"
REQUEST_TIMEOUT = 5
# The API takes at most 16 tags a call
BATCH = 16

# The tags the writes of the current request asked for; None outside a request
_pending: ContextVar[set[str] | None] = ContextVar("edge_purge", default=None)


def event_tag(event_id: int) -> str:
    return f"event-{event_id}"


def start_request() -> set[str]:
    """Start an empty set for the current request and return it."""
    tags: set[str] = set()
    _pending.set(tags)
    return tags


@cache
def _config() -> tuple[str, str, str | None] | None:
    """The token, the project and the team; None when the token or project is unset."""
    token = os.getenv("VERCEL_CACHE_TOKEN")
    project = os.getenv("VERCEL_PROJECT_ID")
    if not token or not project:
        logger.info("edge purge off: VERCEL_CACHE_TOKEN or VERCEL_PROJECT_ID is unset")
        return None
    return token, project, os.getenv("VERCEL_TEAM_ID") or None


def send(tags: Iterable[str]) -> None:
    """Delete the edge copies under these tags; a failure is logged, never raised."""
    config = _config()
    wanted = sorted(tags)
    if config is None or not wanted:
        return
    token, project, team = config
    params = {"projectIdOrName": project}
    if team:
        params["teamId"] = team
    body: dict[str, object] = {}
    # A preview write clears the preview copies only
    if os.getenv("VERCEL_ENV") in ("production", "preview"):
        body["target"] = os.environ["VERCEL_ENV"]
    try:
        for start in range(0, len(wanted), BATCH):
            resp = requests.post(
                API_URL,
                params=params,
                json={**body, "tags": wanted[start : start + BATCH]},
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
    except Exception:
        logger.warning("edge purge failed for %s", ",".join(wanted), exc_info=True)


def _series_tags(session: OrmSession, series: Series | None) -> set[str]:
    if series is None:
        return set()
    tags = {"home", "career"}
    if series.match_id is not None:
        match = session.get(Match, series.match_id)
        if match is not None:
            tags.add(event_tag(match.season_id))
    elif series.round_id is not None:
        round_ = session.get(DBEventRound, series.round_id)
        if round_ is not None and round_.season_id is not None:
            tags.add(event_tag(round_.season_id))
    return tags


def tags_of(session: OrmSession, row: object) -> set[str]:
    """The cache tags whose reads show this row."""
    match row:
        case Series():
            return _series_tags(session, row)
        case (
            SeriesCast()
            | SeriesSide()
            | DBSeriesVetoStep()
            | DBSeriesGame()
            | DBSeriesReplay()
        ):
            return _series_tags(session, session.get(Series, row.series_id))
        case Match():
            return {event_tag(row.season_id), "home", "career"}
        case Season():
            return {event_tag(row.id), "home"} if row.id is not None else set()
        case (
            DBTeamSeason()
            | DBUserTeamSeason()
            | DBTeamSeasonCaptain()
            | DBUserSeasonSignup()
        ):
            return {event_tag(row.season_id)}
        case Team():
            # _collect reads the events of every changed team in one query
            return {"home"}
        case PlayerCareerStats():
            return {"career"}
        case W3CLadderMatch() | LadderSync():
            return {"ladder"}
    return set()


@event.listens_for(Session, "after_flush")
def _collect(session: OrmSession, *_: object) -> None:
    """Keep the tags of every row the flush wrote; the ids of new rows are set by now."""
    rows = [
        *session.new,
        *(row for row in session.dirty if session.is_modified(row)),
        *session.deleted,
    ]
    if not rows:
        return
    tags: set[str] = session.info.setdefault("edge_tags", set())
    with session.no_autoflush:
        for row in rows:
            tags |= tags_of(session, row)
        # A new team plays in no event yet, beyond the rows this flush wrote
        teams = {
            row.id for row in rows if isinstance(row, Team) and row not in session.new
        }
        if teams:
            seasons = session.scalars(
                select(col(DBTeamSeason.season_id)).where(
                    col(DBTeamSeason.team_id).in_(teams)
                )
            )
            tags |= {event_tag(season) for season in seasons}


@event.listens_for(Session, "after_commit")
def _hand_over(session: OrmSession) -> None:
    tags = session.info.pop("edge_tags", None)
    if not tags:
        return
    pending = _pending.get()
    if pending is None:
        send(tags)
    else:
        pending |= tags


@event.listens_for(Session, "after_rollback")
def _forget(session: OrmSession) -> None:
    session.info.pop("edge_tags", None)
