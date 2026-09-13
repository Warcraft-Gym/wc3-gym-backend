"""The events module reads and writes: leagues, events, their stages and phase.

A GNL season is one event of the GNL league, so these reads run over the same
rows the season pages read; the season payloads are unchanged and keep their
own phase word. The event phase is computed on every read and never stored.
"""

import random
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import noload, selectinload
from sqlmodel import col

from app.core.db import Session, rel
from app.core.divisions import cut
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.models.base import ident
from app.models.enums import (
    EntrantKind,
    EventKind,
    Race,
    SeedSource,
    SignupPolicy,
    StageFormat,
)
from app.models.event_division import (
    EventDivision,
    EventDivisionPublic,
    EventDivisionWrite,
)
from app.models.event_entrant import (
    EntrantAdd,
    EntrantPlacement,
    EntrantSignup,
    EventEntrant,
    EventEntrantPublic,
    SeedWrite,
)
from app.models.event_stage import EventStage, EventStagePublic, EventStageWrite
from app.models.league import League, LeagueCreate, LeaguePublic, LeagueUpdate
from app.models.relationships import DBEventRound, DBUserSeasonSignup
from app.models.season import (
    NO_SERIES,
    EventCreate,
    EventPhase,
    EventPublic,
    EventUpdate,
    MemberEventRow,
    Season,
    series_counts,
    series_counts_by_event,
)
from app.models.team import Team
from app.models.team_reduced import TeamReduced
from app.models.types import utcnow
from app.models.user import User, UserPublic


def phase_of(
    session: OrmSession, event: Season, counts: tuple[int, int, int] | None = None
) -> EventPhase:
    """The phase of an event, read off what is stored rather than a status column.

    The rungs run from the last one back: an unpublished event is a draft, an
    event whose series are all scored or whose end date has passed is
    finished, one with a series started is running, then the signup window and
    the check-in window of the first round. Seeded is the resting rung.
    Pass `counts` to reuse one grouped series count over a page of events.
    """
    if not event.published:
        return "draft"
    total, started, scored = (
        counts if counts is not None else series_counts(session, event.id)
    )
    if (total and total == scored) or (event.end_date and event.end_date < _today()):
        return "finished"
    if started:
        return "running"
    if event.signups_open:
        return "signups_open"
    if event.checkin_enabled and checkin_open(event):
        return "checkin"
    return "seeded"


def checkin_open(event: Season) -> bool:
    """Whether the check-in window of the event's first round stands open.

    The window opens `checkin_days` before the round starts and closes when
    the round ends; a blank `checkin_days` keeps it open. An event with no
    rounds has nothing to check into.
    """
    # The relationship orders the rounds by playday, so the first is the earliest
    first = next(iter(event.rounds), None)
    if first is None:
        return False
    if event.checkin_days is None or first.start_date is None:
        return True
    now = _today()
    return first.start_date - timedelta(days=event.checkin_days) <= now and (
        first.end_date is None or now <= first.end_date
    )


def _today() -> date:
    return utcnow().date()


class EventService:
    def get_all(
        self,
        kind: EventKind | None = None,
        league_id: int | None = None,
        published: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[EventPublic]:
        """One page of events, newest first, each with its computed phase."""
        statement = select(Season).order_by(col(Season.id).desc())
        if kind is not None:
            statement = statement.where(col(Season.kind) == kind)
        if league_id is not None:
            statement = statement.where(col(Season.league_id) == league_id)
        if published is not None:
            statement = statement.where(col(Season.published).is_(published))
        with Session.begin() as session:
            events = session.scalars(statement.offset(offset).limit(limit)).all()
            return _publics(session, events)

    def get(self, event_id: int) -> EventPublic:
        """One event with its stages, its divisions and how many entrants it holds."""
        with Session.begin() as session:
            return _public(session, _event(session, event_id), full=True)

    def add(self, data: EventCreate) -> EventPublic:
        """Create an event and the stages it plays, or one default stage."""
        with Session.begin() as session:
            fields = data.model_dump(exclude={"stages"})
            if fields.get("entrant_kind") is None:
                fields["entrant_kind"] = _league_entrant_kind(
                    session, fields.get("league_id")
                )
            event = Season(**fields)
            session.add(event)
            session.flush()
            _write_stages(session, event, data.stages)
            return _public(session, event, full=True)

    def update(self, event_id: int, data: EventUpdate) -> EventPublic:
        """Change the event fields the body names; the stages have their own route."""
        with Session.begin() as session:
            event = _event(session, event_id)
            event.sqlmodel_update(data.model_dump(exclude_unset=True))
            session.flush()
            return _public(session, event, full=True)

    def set_stages(
        self, event_id: int, stages: Sequence[EventStageWrite]
    ) -> EventPublic:
        """Write the event's stage list; the order of the body is the order played.

        The stage at a position is updated in place, so its id holds and the
        rounds, fixtures and series that name it stay. Positions past the end
        are added, and a stage the shorter list drops is refused if it still
        holds rounds.
        """
        with Session.begin() as session:
            event = _event(session, event_id)
            rows = list(stages) or [_default_stage(event)]
            current = list(
                session.scalars(
                    select(EventStage)
                    .where(col(EventStage.event_id) == event_id)
                    .order_by(col(EventStage.position))
                )
            )
            for row, stage in zip(current, rows, strict=False):
                row.sqlmodel_update(stage.model_dump())
            dropped = current[len(rows) :]
            if dropped:
                _refuse_rounds(session, dropped)
                for row in dropped:
                    session.delete(row)
            if len(rows) > len(current):
                _write_stages(
                    session, event, rows[len(current) :], start=len(current) + 1
                )
            session.flush()
            return _public(session, event, full=True)

    def get_leagues(self) -> list[LeaguePublic]:
        """Every league, without its events."""
        with Session.begin() as session:
            leagues = session.scalars(select(League).order_by(col(League.id))).all()
            return [LeaguePublic.model_validate(league) for league in leagues]

    def get_league(self, league_id: int) -> LeaguePublic:
        """One league and the events that are its runs, newest first."""
        with Session.begin() as session:
            league = session.get(League, league_id)
            if league is None:
                raise NotFoundError(f"League not found by id: {league_id}")
            events = session.scalars(
                select(Season)
                .where(col(Season.league_id) == league_id)
                .order_by(col(Season.id).desc())
            ).all()
            public = LeaguePublic.model_validate(league)
            public.events = _nested(_publics(session, events))
            return public

    def add_league(self, data: LeagueCreate) -> LeaguePublic:
        with Session.begin() as session:
            league = League(**data.model_dump())
            session.add(league)
            session.flush()
            return LeaguePublic.model_validate(league)

    def update_league(self, league_id: int, data: LeagueUpdate) -> LeaguePublic:
        with Session.begin() as session:
            league = session.get(League, league_id)
            if league is None:
                raise NotFoundError(f"League not found by id: {league_id}")
            league.sqlmodel_update(data.model_dump(exclude_unset=True))
            session.flush()
            return LeaguePublic.model_validate(league)

    def events_for_member(self, user_id: int | None) -> list[MemberEventRow]:
        """The member home's published events, newest first, every kind in one list.

        One function over the event rows replaces the season and KOTH split.
        `joined` is the caller's own; a caller with no id has joined nothing.
        """
        with Session.begin() as session:
            events = session.scalars(
                select(Season)
                .where(col(Season.published).is_(True))
                .order_by(col(Season.id).desc())
            ).all()
            joined = _joined_events(session, user_id)
            counts = series_counts_by_event(session, [event.id for event in events])
            return [
                MemberEventRow(
                    kind=event.kind,
                    id=ident(event),
                    name=event.name,
                    league_short_name=event.league_short_name,
                    start=event.start_date or _day(event),
                    end=event.end_date,
                    phase=phase_of(session, event, counts.get(event.id, NO_SERIES)),
                    signups_open=event.signups_open,
                    joined=event.id in joined,
                    url=event.page_url,
                )
                for event in events
            ]

    # ============ Entrants ============
    def get_entrants(self, event_id: int) -> list[EventEntrantPublic]:
        """Every entrant of the event, seeded ones first, with their warnings."""
        with Session.begin() as session:
            event = _event(session, event_id)
            rows = session.scalars(
                select(EventEntrant)
                .where(col(EventEntrant.event_id) == event_id)
                .order_by(col(EventEntrant.seed).nulls_last(), col(EventEntrant.id))
            ).all()
            return _entrant_publics(session, event, rows)

    def add_entrant(
        self, event_id: int, data: EntrantSignup, claims: dict[str, Any] | None
    ) -> EventEntrantPublic:
        """Sign the caller up, or the team the caller captains."""
        with Session.begin() as session:
            event = _event(session, event_id)
            if not event.signups_open:
                raise BadRequestError("Signups are closed for this event")
            if data.team_id is not None:
                if not _is_admin(claims) and data.team_id not in _captains(claims):
                    raise ApiError(
                        403, {"error": "Only a captain of the team enters it"}
                    )
                row = _enter(session, event, data, team_id=data.team_id)
            else:
                row = _enter(
                    session,
                    event,
                    data,
                    user_id=ident(_signup_user(session, event, data, claims)),
                )
            return _entrant_publics(session, event, [row])[0]

    def add_entrant_as_admin(
        self, event_id: int, data: EntrantAdd
    ) -> EventEntrantPublic:
        """Enter any player or team, whether signups stand open or not."""
        with Session.begin() as session:
            event = _event(session, event_id)
            if data.team_id is not None:
                row = _enter(session, event, data, team_id=data.team_id)
            else:
                row = _enter(
                    session, event, data, user_id=ident(_named_user(session, data))
                )
            return _entrant_publics(session, event, [row])[0]

    def withdraw(self, event_id: int, claims: dict[str, Any] | None) -> None:
        """Stamp the caller's own entrant row as withdrawn; the row stays."""
        with Session.begin() as session:
            event = _event(session, event_id)
            user = _caller(session, claims)
            row = (
                None
                if user is None
                else session.scalars(
                    select(EventEntrant).where(
                        col(EventEntrant.event_id) == event.id,
                        col(EventEntrant.user_id) == user.id,
                    )
                ).first()
            )
            if row is None or row.withdrawn_at is not None:
                raise NotFoundError("No signup to withdraw")
            row.withdrawn_at = utcnow()

    def check_in(
        self, event_id: int, entrant_id: int, claims: dict[str, Any] | None
    ) -> EventEntrantPublic:
        """Stamp an entrant as checked in: the caller's own row, or an admin's call."""
        with Session.begin() as session:
            event = _event(session, event_id)
            row = _entrant(session, event_id, entrant_id)
            if not _is_admin(claims):
                user = _caller(session, claims)
                if user is None or row.user_id != user.id:
                    raise ApiError(403, {"error": "Check in your own signup"})
            row.checked_in_at = utcnow()
            session.flush()
            return _entrant_publics(session, event, [row])[0]

    def remove_entrant(self, event_id: int, entrant_id: int) -> None:
        """Delete one entrant row; an admin removes what a withdrawal would keep."""
        with Session.begin() as session:
            session.delete(_entrant(session, event_id, entrant_id))

    def place_entrant(
        self, event_id: int, entrant_id: int, data: EntrantPlacement
    ) -> EventEntrantPublic:
        """Move one entrant into a division; the move is placement by hand."""
        with Session.begin() as session:
            event = _event(session, event_id)
            row = _entrant(session, event_id, entrant_id)
            if data.division_id is not None:
                division = session.get(EventDivision, data.division_id)
                if division is None or division.event_id != event_id:
                    raise BadRequestError(
                        f"Division not found by id: {data.division_id}"
                    )
            row.division_id = data.division_id
            row.manual_placement = data.manual_placement
            session.flush()
            return _entrant_publics(session, event, [row])[0]

    # ============ Divisions and seeds ============
    def set_divisions(
        self, event_id: int, divisions: Sequence[EventDivisionWrite]
    ) -> EventPublic:
        """Replace the division list; the order of the body is their position."""
        with Session.begin() as session:
            event = _event(session, event_id)
            session.execute(
                update(EventEntrant)
                .where(col(EventEntrant.event_id) == event_id)
                .values(division_id=None, manual_placement=False)
            )
            session.execute(
                delete(EventDivision).where(col(EventDivision.event_id) == event_id)
            )
            session.add_all(
                EventDivision(event_id=event_id, position=position, **row.model_dump())
                for position, row in enumerate(divisions, start=1)
            )
            session.flush()
            return _public(session, event, full=True)

    def assign_divisions(self, event_id: int) -> EventPublic:
        """Cut the entrants into the divisions from the MMR of their signup race.

        An entrant an admin placed by hand keeps the division it was given.
        The answer carries the divisions with the entrants each now holds.
        """
        with Session.begin() as session:
            event = _event(session, event_id)
            divisions = _divisions(session, event_id)
            if not divisions:
                raise BadRequestError("The event has no divisions to assign")
            rows = [
                row
                for row in _live_entrants(session, event_id)
                if not row.manual_placement
            ]
            mmrs = _mmrs(session, rows)
            bands = cut(
                [(ident(row), mmrs[ident(row)]) for row in rows],
                [(division.lower_bound, division.size) for division in divisions],
            )
            for row in rows:
                row.division_id = divisions[bands[ident(row)]].id
            session.flush()
            return _public(session, event, full=True)

    def set_seeds(
        self, event_id: int, stage_id: int, data: SeedWrite
    ) -> list[EventEntrantPublic]:
        """Number the entrants 1..n inside each division and stamp the source."""
        with Session.begin() as session:
            event = _event(session, event_id)
            stage = _stage(session, event_id, stage_id)
            if stage.seeds_locked_at is not None:
                raise BadRequestError("The seeds of this stage are locked")
            rows = _live_entrants(session, event_id)
            mmrs = _mmrs(session, rows)
            taken: dict[int | None, int] = {}
            for row in _seed_order(rows, mmrs, data):
                taken[row.division_id] = taken.get(row.division_id, 0) + 1
                row.seed = taken[row.division_id]
                row.seed_source = data.source.value
                row.mmr_at_seed = mmrs[ident(row)]
            session.flush()
            rows.sort(key=lambda row: (row.division_id or 0, row.seed or 0))
            return _entrant_publics(session, event, rows)

    def lock_seeds(self, event_id: int, stage_id: int) -> EventStagePublic:
        """Stamp the stage as locked; a later seed write is refused."""
        with Session.begin() as session:
            stage = _stage(session, event_id, stage_id)
            stage.seeds_locked_at = utcnow()
            session.flush()
            return EventStagePublic.model_validate(stage)


def _nested(events: list[EventPublic]) -> list[EventPublic]:
    """The league's events with each child under its parent, parents in order.

    A qualifier is a child of the event it feeds, so the league page lists the
    run once and its qualifiers inside it. A child whose parent is not in the
    list stays where it is.
    """
    by_id = {event.id: event for event in events}
    for event in events:
        parent = by_id.get(event.parent_id) if event.parent_id else None
        if parent is not None:
            parent.children.append(event)
    return [
        event for event in events if not event.parent_id or event.parent_id not in by_id
    ]


def _league_entrant_kind(session: OrmSession, league_id: int | None) -> EntrantKind:
    """The entrant kind a new event copies from its league; solo without one."""
    league = session.get(League, league_id) if league_id else None
    return league.entrant_kind if league else EntrantKind.solo


def _event(session: OrmSession, event_id: int) -> Season:
    event = session.get(Season, event_id)
    if event is None:
        raise NotFoundError(f"Event not found by id: {event_id}")
    return event


def _stage(session: OrmSession, event_id: int, stage_id: int) -> EventStage:
    stage = session.get(EventStage, stage_id)
    if stage is None or stage.event_id != event_id:
        raise NotFoundError(f"Stage not found by id: {stage_id}")
    return stage


def _divisions(session: OrmSession, event_id: int) -> list[EventDivision]:
    """The event's divisions, the strongest first."""
    return list(
        session.scalars(
            select(EventDivision)
            .where(col(EventDivision.event_id) == event_id)
            .order_by(col(EventDivision.position))
        )
    )


def _live_entrants(session: OrmSession, event_id: int) -> list[EventEntrant]:
    """Every entrant of the event that has not withdrawn, in signup order."""
    return list(
        session.scalars(
            select(EventEntrant)
            .where(
                col(EventEntrant.event_id) == event_id,
                col(EventEntrant.withdrawn_at).is_(None),
            )
            .order_by(col(EventEntrant.id))
        )
    )


def _write_stages(
    session: OrmSession,
    event: Season,
    stages: Sequence[EventStageWrite],
    start: int = 1,
) -> None:
    """Write the stages in the order the body gives them, or one default stage.

    `start` is the position of the first one, so a longer list appends.
    """
    rows = list(stages) or [_default_stage(event)]
    session.add_all(
        EventStage(event_id=ident(event), position=position, **stage.model_dump())
        for position, stage in enumerate(rows, start=start)
    )
    session.flush()


def _refuse_rounds(session: OrmSession, dropped: Sequence[EventStage]) -> None:
    """Refuse to drop a stage that still holds rounds.

    A round takes its fixtures, series and answers with it, so a list that
    shortens past a scheduled stage would take the results too.
    """
    stages = {ident(stage): stage for stage in dropped}
    held = sorted(
        stage_id
        for stage_id in session.scalars(
            select(col(DBEventRound.stage_id))
            .where(col(DBEventRound.stage_id).in_(stages))
            .distinct()
        )
        if stage_id is not None
    )
    if held:
        names = ", ".join(
            stages[stage_id].name or str(stages[stage_id].position) for stage_id in held
        )
        raise BadRequestError(
            f"stage {names} still holds rounds; delete them before the list shortens"
        )


def _default_stage(event: Season) -> EventStageWrite:
    """The stage an event with no stage list plays: its own maps, round robin."""
    rules = event.map_rules.split(",") if event.map_rules else []
    return EventStageWrite(
        format=StageFormat.round_robin,
        best_of=len(rules) or 3,
        map_rules=event.map_rules,
    )


def _day(event: Season) -> date | None:
    """The day a cup or a KOTH night starts, for an event that carries no dates."""
    return event.starts_at.date() if event.starts_at else None


def _joined_events(session: OrmSession, user_id: int | None) -> set[int]:
    """The events the player entered: an entrant row, or a GNL season signup."""
    if user_id is None:
        return set()
    entered = session.scalars(
        select(col(EventEntrant.event_id)).where(
            col(EventEntrant.user_id) == user_id,
            col(EventEntrant.withdrawn_at).is_(None),
        )
    )
    signed = session.scalars(
        select(col(DBUserSeasonSignup.season_id)).where(
            col(DBUserSeasonSignup.user_id) == user_id
        )
    )
    return set(entered) | set(signed)


def _publics(session: OrmSession, events: Sequence[Season]) -> list[EventPublic]:
    """A page of event payloads, with one grouped series count behind their phases."""
    counts = series_counts_by_event(session, [event.id for event in events])
    return [
        _public(session, event, counts=counts.get(event.id, NO_SERIES))
        for event in events
    ]


def _public(
    session: OrmSession,
    event: Season,
    full: bool = False,
    counts: tuple[int, int, int] | None = None,
) -> EventPublic:
    """One event payload; the stages, the divisions and the entrant count only
    when it is the subject of the read.
    """
    public = EventPublic.model_validate(event)
    public.phase = phase_of(session, event, counts)
    if not full:
        return public
    public.stages = [
        EventStagePublic.model_validate(row)
        for row in session.scalars(
            select(EventStage)
            .where(col(EventStage.event_id) == event.id)
            .order_by(col(EventStage.position))
        )
    ]
    by_division = {
        division_id: total
        for division_id, total in session.execute(
            select(col(EventEntrant.division_id), func.count())
            .where(
                col(EventEntrant.event_id) == event.id,
                col(EventEntrant.withdrawn_at).is_(None),
            )
            .group_by(col(EventEntrant.division_id))
        )
    }
    public.divisions = [
        EventDivisionPublic.model_validate(
            row, update={"entrant_count": by_division.get(row.id, 0)}
        )
        for row in _divisions(session, ident(event))
    ]
    public.entrant_count = session.scalar(
        select(func.count())
        .select_from(EventEntrant)
        .where(
            col(EventEntrant.event_id) == event.id,
            col(EventEntrant.withdrawn_at).is_(None),
        )
    )
    # The qualifiers that feed this event, newest first
    public.children = [
        EventPublic.model_validate(row)
        for row in session.scalars(
            select(Season)
            .where(col(Season.parent_id) == event.id)
            .order_by(col(Season.id).desc())
        )
    ]
    return public


def _is_admin(claims: dict[str, Any] | None) -> bool:
    """Whether those claims carry the admin role, or the admin access token."""
    return bool(claims) and (
        claims.get("role") == "admin" or claims.get("sub") == "admin"
    )


def _captains(claims: dict[str, Any] | None) -> set[int]:
    """The teams the caller captains, from the seats the login resolved."""
    return {seat["team_id"] for seat in (claims or {}).get("seats", [])}


def _caller(session: OrmSession, claims: dict[str, Any] | None) -> User | None:
    """The player row behind the session, found by the Discord id of its login."""
    discord_id = (claims or {}).get("sub")
    if not discord_id or discord_id == "admin":
        return None
    return session.scalars(
        select(User).where(col(User.discordId) == discord_id)
    ).first()


def _by_battle_tag(session: OrmSession, battle_tag: str, race: Race) -> User:
    """The player row with that battle tag, created when the tag is new.

    An `anyone` event takes a battle tag the way the KOTH chat command does,
    so a player with no account still enters and keeps one row across events.
    """
    tag = battle_tag.strip()
    folded = func.lower(func.trim(col(User.battleTag)))
    user = session.scalars(select(User).where(folded == tag.lower())).first()
    if user is not None:
        return user
    user = User(
        name=tag.split("#")[0] or tag,
        battleTag=tag,
        discordTag="",
        discordId="",
        race=race,
    )
    session.add(user)
    session.flush()
    return user


def _stats_for(user: User, race: Race) -> tuple[int | None, int]:
    """The player's newest W3C rating on that race, and the games behind it.

    The rating is the one the newest stored W3C season carries; the games are
    every season the app has synced for that race, because a min-games rule
    asks how much the player has played, not how much this season.
    """
    rows = [stat for stat in (user.w3c_stats or []) if stat.race == race]
    if not rows:
        return None, 0
    newest = max(rows, key=lambda stat: stat.wc3_season)
    return newest.mmr, sum(stat.games or 0 for stat in rows)


def _warnings(
    event: Season, user: User | None, mmr: int | None, games: int
) -> list[str]:
    """What an admin should look at on this entrant; none of it refused the signup."""
    warnings = []
    if user is not None and event.min_games is not None and games < event.min_games:
        warnings.append("under_min_games")
    if event.mmr_max is not None and mmr is not None and mmr > event.mmr_max:
        warnings.append("over_mmr_max")
    if user is not None and user.banned_at is not None:
        warnings.append("banned")
    return warnings


def _entrant_publics(
    session: OrmSession, event: Season, rows: Sequence[EventEntrant]
) -> list[EventEntrantPublic]:
    """The entrant payloads of one event, with the players and teams behind them.

    Two reads fill every row: the players with their W3C stats, and the teams.
    """
    team_ids = {row.team_id for row in rows if row.team_id}
    users = _users_for(session, rows)
    teams = {
        team.id: team
        for team in session.scalars(select(Team).where(col(Team.id).in_(team_ids)))
    }
    return [_entrant_public(event, row, users, teams) for row in rows]


def _users_for(
    session: OrmSession, rows: Sequence[EventEntrant]
) -> dict[int | None, User]:
    """The players behind those entrant rows, with the W3C stats their MMR reads."""
    user_ids = {row.user_id for row in rows if row.user_id}
    return {
        user.id: user
        for user in session.scalars(
            select(User)
            .options(
                selectinload(rel(User.w3c_stats)),
                noload(rel(User.team_seasons)),
                noload(rel(User.signup_seasons)),
            )
            .where(col(User.id).in_(user_ids))
        ).unique()
    }


def _mmrs(session: OrmSession, rows: Sequence[EventEntrant]) -> dict[int, int | None]:
    """Each entrant against the rating of the race it signed up on; a team has none."""
    users = _users_for(session, rows)
    return {
        ident(row): _stats_for(users[row.user_id], row.race)[0]
        if row.user_id in users
        else None
        for row in rows
    }


def _by_mmr(
    rows: Sequence[EventEntrant], mmrs: dict[int, int | None]
) -> list[EventEntrant]:
    """The entrants strongest first, the signup order breaking a tie."""
    return sorted(rows, key=lambda row: (-(mmrs[ident(row)] or 0), ident(row)))


def _seed_order(
    rows: Sequence[EventEntrant], mmrs: dict[int, int | None], data: SeedWrite
) -> list[EventEntrant]:
    """The whole entrant list in seed order; the stage numbers it per division.

    The two sources that read standings wait for the stage engine and refuse
    with `not_built`. An entrant the order list leaves out follows on MMR.
    """
    if data.source in (SeedSource.previous_stage, SeedSource.qualifier):
        raise ApiError(
            400,
            {
                "error": "not_built",
                "message": f"Seeding from {data.source.value} lands with the engine",
            },
        )
    if data.source is SeedSource.random:
        shuffled = list(rows)
        random.shuffle(shuffled)
        return shuffled
    if data.source not in (SeedSource.manual, SeedSource.invitation):
        return _by_mmr(rows, mmrs)
    named = data.order or []
    if not named and data.source is SeedSource.manual:
        raise BadRequestError("Manual seeding takes an order of entrant ids")
    by_id = {ident(row): row for row in rows}
    unknown = [entrant_id for entrant_id in named if entrant_id not in by_id]
    if unknown:
        raise BadRequestError(f"Not an entrant of this event: {unknown[0]}")
    rest = [row for row in rows if ident(row) not in set(named)]
    return [by_id[entrant_id] for entrant_id in named] + _by_mmr(rest, mmrs)


def _entrant_public(
    event: Season,
    row: EventEntrant,
    users: dict[int | None, User],
    teams: dict[int | None, Team],
) -> EventEntrantPublic:
    """One entrant payload: the identity, the rating on the signup race, the warnings."""
    user = users.get(row.user_id)
    team = teams.get(row.team_id)
    mmr, games = _stats_for(user, row.race) if user else (None, 0)
    return EventEntrantPublic(
        id=ident(row),
        event_id=row.event_id,
        user=UserPublic.from_user(user) if user else None,
        team=TeamReduced.from_team(team) if team else None,
        race=row.race,
        channel=row.channel,
        mmr=mmr,
        mmr_synced_at=user.w3c_synced_at if user else None,
        warnings=_warnings(event, user, mmr, games),
        seed=row.seed,
        seed_source=row.seed_source,
        mmr_at_seed=row.mmr_at_seed,
        division_id=row.division_id,
        manual_placement=row.manual_placement,
        checked_in_at=row.checked_in_at,
        withdrawn_at=row.withdrawn_at,
        qualified_from_event_id=row.qualified_from_event_id,
    )


def _entrant(session: OrmSession, event_id: int, entrant_id: int) -> EventEntrant:
    row = session.get(EventEntrant, entrant_id)
    if row is None or row.event_id != event_id:
        raise NotFoundError(f"Entrant not found by id: {entrant_id}")
    return row


def _signup_user(
    session: OrmSession,
    event: Season,
    data: EntrantSignup,
    claims: dict[str, Any] | None,
) -> User:
    """The player a self signup enters: the battle tag, or the session's own row."""
    if event.signup_policy is SignupPolicy.anyone and data.battle_tag:
        return _by_battle_tag(session, data.battle_tag, data.race)
    if claims is None:
        raise ApiError(401, {"error": "Missing Authorization Header"})
    user = _caller(session, claims)
    if user is None:
        raise ApiError(
            403, {"error": "No player profile is linked to this Discord account"}
        )
    return user


def _named_user(session: OrmSession, data: EntrantAdd) -> User:
    """The player an admin names: a user id, or a battle tag to find or create."""
    if data.user_id is not None:
        user = session.get(User, data.user_id)
        if user is None:
            raise NotFoundError(f"User not found by id: {data.user_id}")
        return user
    if data.battle_tag:
        return _by_battle_tag(session, data.battle_tag, data.race)
    raise BadRequestError("Name a user_id, a battle_tag or a team_id")


def _enter(
    session: OrmSession,
    event: Season,
    data: EntrantSignup,
    user_id: int | None = None,
    team_id: int | None = None,
) -> EventEntrant:
    """Write the entrant row, or reopen the one that withdrew.

    GNL entrants stay on the season signup table this wave, so a GNL event
    refuses here. A full event refuses too: no waiting list is kept.
    """
    if event.kind is EventKind.gnl:
        raise BadRequestError(
            f"A GNL season takes its signups at /seasons/{event.id}/signups"
        )
    side = (
        col(EventEntrant.user_id) == user_id
        if user_id is not None
        else col(EventEntrant.team_id) == team_id
    )
    existing = session.scalars(
        select(EventEntrant).where(col(EventEntrant.event_id) == event.id, side)
    ).first()
    if existing is not None and existing.withdrawn_at is None:
        raise BadRequestError("This entrant is already signed up")
    _room_for_one_more(session, event)
    if existing is not None:
        # The unique key is one row per entrant, so a return signup reopens it
        existing.withdrawn_at = None
        existing.race = data.race
        existing.channel = data.channel
        session.flush()
        return existing
    row = EventEntrant(
        event_id=ident(event),
        user_id=user_id,
        team_id=team_id,
        race=data.race,
        channel=data.channel,
    )
    session.add(row)
    session.flush()
    return row


def _room_for_one_more(session: OrmSession, event: Season) -> None:
    """Refuse the signup that would pass the entrant cap; nothing waits in line."""
    if event.entrant_cap is None:
        return
    taken = session.scalar(
        select(func.count())
        .select_from(EventEntrant)
        .where(
            col(EventEntrant.event_id) == event.id,
            col(EventEntrant.withdrawn_at).is_(None),
        )
    )
    if taken is not None and taken >= event.entrant_cap:
        raise BadRequestError(f"The event is full at {event.entrant_cap} entrants")
