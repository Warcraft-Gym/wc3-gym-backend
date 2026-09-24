"""A write clears the edge copies of the reads it changes.

Each edge-cached read names its cache tags in the Vercel-Cache-Tag header:
`event-{id}` on the reads of one event, and one tag per global list
(`home`, `career`, `ladder`). A session listener maps every flushed row to
the tags it feeds, keeps them on the session until the commit, and hands
them to the request; the middleware in app/main.py asks Vercel to clear
them once the response is sent. A bulk statement the listener cannot see
names its tags with `add` or `add_users` beside it. A rollback drops them. Outside a request,
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
from sqlalchemy import event, select, union
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm.attributes import instance_state
from sqlmodel import col

from app.core.db import Session
from app.models.ladder_sync import LadderSync
from app.models.map import Map
from app.models.match import Match
from app.models.player_career_stats import PlayerCareerStats
from app.models.relationships import (
    DBEventRound,
    DBMapSeason,
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
from app.models.user import User
from app.models.user_battle_tag import UserBattleTag
from app.models.user_team_season import DBUserTeamSeason
from app.models.w3c_ladder_match import W3CLadderMatch

logger = logging.getLogger(__name__)

API = "https://api.vercel.com/v1/edge-cache"
# The global lists are read on every visit: an invalidated copy is served while
# it refills, so a burst of readers never waits on the function
HOT = frozenset({"home", "career", "ladder"})
# An event copy is deleted, so the player who reports a result reads it at once
INVALIDATE = f"{API}/invalidate-by-tags"
DELETE = f"{API}/dangerously-delete-by-tags"
REQUEST_TIMEOUT = 5
# The API takes at most 16 tags a call
BATCH = 16
# The series fields a career total reads
CAREER_FIELDS = (
    "player1_score",
    "player2_score",
    "result_kind",
    "player1_id",
    "player2_id",
)

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
    """Clear the edge copies under these tags; a failure is logged, never raised."""
    config = _config()
    wanted = set(tags)
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
    for url, group in ((INVALIDATE, wanted & HOT), (DELETE, wanted - HOT)):
        ordered = sorted(group)
        try:
            for start in range(0, len(ordered), BATCH):
                resp = requests.post(
                    url,
                    params=params,
                    json={**body, "tags": ordered[start : start + BATCH]},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
        except Exception:
            logger.warning("edge purge failed for %s", ",".join(ordered), exc_info=True)


def add(session: OrmSession, *tags: str) -> None:
    """Name tags a bulk statement changes; they go out with the commit."""
    session.info.setdefault("edge_tags", set()).update(tags)


def _old(row: object, attr: str) -> list[int]:
    """The values this flush replaced on a column: a row that moved names its old place."""
    return [value for value in instance_state(row).attrs[attr].history.deleted if value]


def _series_events(session: OrmSession, series: Series) -> set[str]:
    """The event of the series' fixture, or of its round when it has none;
    the old one too when this flush moved it."""
    tags = set()
    for match_id in filter(None, [series.match_id, *_old(series, "match_id")]):
        match = session.get(Match, match_id)
        if match is not None:
            tags.add(event_tag(match.season_id))
    rounds = [*_old(series, "round_id")]
    if series.match_id is None and series.round_id is not None:
        rounds.append(series.round_id)
    for round_id in rounds:
        round_ = session.get(DBEventRound, round_id)
        if round_ is not None and round_.season_id is not None:
            tags.add(event_tag(round_.season_id))
    return tags


def series_tags(session: OrmSession, series: Series | None) -> set[str]:
    """The series' event, and its old event when it moved; `home` shows every series."""
    if series is None:
        return set()
    return {"home", *_series_events(session, series)}


def tags_of(session: OrmSession, row: object, whole: bool = False) -> set[str]:
    """The cache tags whose reads show this row; `whole` for an insert or a delete.

    A user, a battle tag, a team and a map reach their events through links
    that _links reads for the whole flush. A settings row names no tag: the
    score system changes by hand, rarely, and the copies live out s-maxage.
    """
    match row:
        case Series():
            tags = series_tags(session, row)
            state = instance_state(row)
            if whole or any(
                state.attrs[name].history.has_changes() for name in CAREER_FIELDS
            ):
                tags.add("career")
            return tags
        case DBSeriesGame():
            return series_tags(session, session.get(Series, row.series_id)) | {"career"}
        case SeriesCast() | SeriesSide() | DBSeriesVetoStep() | DBSeriesReplay():
            return series_tags(session, session.get(Series, row.series_id))
        case Match():
            return {event_tag(row.season_id), "home"}
        case Season():
            return {event_tag(row.id), "home"} if row.id is not None else set()
        case DBTeamSeason():
            return {event_tag(s) for s in (row.season_id, *_old(row, "season_id"))}
        case DBUserTeamSeason() | DBTeamSeasonCaptain() | DBUserSeasonSignup():
            return {event_tag(row.season_id)}
        case Team():
            return {"home"}
        case User() | UserBattleTag():
            return {"home", "career", "ladder"}
        case PlayerCareerStats():
            return {"career"}
        case W3CLadderMatch() | LadderSync():
            return {"ladder"}
    return set()


def user_events(session: OrmSession, user_ids: Iterable[int]) -> set[str]:
    """The events where these players hold a roster seat or a signup, in one query."""
    ids = set(user_ids)
    if not ids:
        return set()
    stmt = union(
        select(col(DBUserTeamSeason.season_id)).where(
            col(DBUserTeamSeason.user_id).in_(ids)
        ),
        select(col(DBUserSeasonSignup.season_id)).where(
            col(DBUserSeasonSignup.user_id).in_(ids)
        ),
    )
    return {event_tag(season) for season in session.scalars(stmt)}


def add_users(session: OrmSession, user_ids: Iterable[int]) -> None:
    """Name the tags a bulk statement on these players changes: the global
    lists and their events. A failed lookup is logged and names the lists only."""
    add(session, *HOT)
    try:
        add(session, *user_events(session, user_ids))
    except Exception:
        logger.warning("edge purge: the players' events were not read", exc_info=True)


def _map_events(session: OrmSession, map_ids: set[int]) -> set[str]:
    """The events that use these maps: a fixed map, the pool, a round, a veto step."""
    stmt = union(
        select(col(Match.season_id)).where(col(Match.fixed_map_id).in_(map_ids)),
        select(col(DBMapSeason.season_id)).where(col(DBMapSeason.map_id).in_(map_ids)),
        select(col(DBEventRound.season_id)).where(
            col(DBEventRound.map_id).in_(map_ids)
        ),
        select(col(Match.season_id))
        .join(Series, col(Series.match_id) == col(Match.id))
        .join(DBSeriesVetoStep, col(DBSeriesVetoStep.series_id) == col(Series.id))
        .where(col(DBSeriesVetoStep.map_id).in_(map_ids)),
    )
    return {event_tag(season) for season in session.scalars(stmt) if season}


def _team_events(session: OrmSession, team_ids: set[int]) -> set[str]:
    seasons = session.scalars(
        select(col(DBTeamSeason.season_id)).where(
            col(DBTeamSeason.team_id).in_(team_ids)
        )
    )
    return {event_tag(season) for season in seasons}


@event.listens_for(Session, "before_flush")
def _links(session: OrmSession, *_: object) -> None:
    """Read the events of every changed player, team and map before the flush,
    while a deleted row's links still stand. A new row has no link yet."""
    users: set[int] = set()
    teams: set[int] = set()
    maps: set[int] = set()
    for row in (*session.dirty, *session.deleted):
        if row not in session.deleted and not session.is_modified(row):
            continue
        match row:
            case User() if row.id is not None:
                users.add(row.id)
            case UserBattleTag():
                users.update([row.user_id, *_old(row, "user_id")])
            case Team() if row.id is not None:
                teams.add(row.id)
            case Map() if row.id is not None:
                maps.add(row.id)
    if not (users or teams or maps):
        return
    tags: set[str] = session.info.setdefault("edge_tags", set())
    with session.no_autoflush:
        for lookup, ids in (
            (user_events, users),
            (_team_events, teams),
            (_map_events, maps),
        ):
            if not ids:
                continue
            try:
                tags |= lookup(session, ids)
            except Exception:
                logger.warning("edge purge: a tag lookup failed", exc_info=True)


@event.listens_for(Session, "after_flush")
def _collect(session: OrmSession, *_: object) -> None:
    """Keep the tags of every row the flush wrote; the ids of new rows are set by now.

    A row whose tags fail to compute is logged and names none; the write goes on.
    """
    whole = [*session.new, *session.deleted]
    rows = [
        *((row, True) for row in whole),
        *((row, False) for row in session.dirty if session.is_modified(row)),
    ]
    if not rows:
        return
    tags: set[str] = session.info.setdefault("edge_tags", set())
    with session.no_autoflush:
        for row, is_whole in rows:
            try:
                tags |= tags_of(session, row, is_whole)
            except Exception:
                logger.warning(
                    "edge purge: no tags for %s", type(row).__name__, exc_info=True
                )


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
