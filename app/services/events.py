"""The events module reads and writes: leagues, events, their stages and phase.

A GNL season is one event of the GNL league, so these reads run over the same
rows the season pages read; the season payloads are unchanged and keep their
own phase word. The event phase is computed on every read and never stored.
"""

import random
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import noload, selectinload
from sqlmodel import col

from app.core.availability import availability_hint
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
from app.models.relationships import (
    DBEventRound,
    DBUserSeasonSignup,
    EventRoundPublic,
)
from app.models.round_availability import DBRoundAvailability
from app.models.season import (
    NO_SERIES,
    AvailabilityHint,
    EventCreate,
    EventPhase,
    EventPublic,
    EventUpdate,
    MemberAction,
    MemberEventRow,
    Season,
    series_counts,
    series_counts_by_event,
)
from app.models.settings import Settings
from app.models.team import Team
from app.models.team_reduced import TeamReduced
from app.models.types import utcnow
from app.models.user import User, UserPublic
from app.models.user_team_season import DBUserTeamSeason
from app.models.w3c_stats import W3CStats
from app.services import stage_engine

# How many W3C seasons back a rating is still the player's current one
SEASONS = 3

# The setting that names the W3C season the app is on
W3C_SEASON_KEY = "current_w3c_season"


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


def next_round(event: Season) -> DBEventRound | None:
    """The next dated round of the event: the earliest one that is not over.

    A round with no dates is no round to check into, and a stage that holds no
    rounds at all leaves the event checking in to itself.
    """
    now = _today()
    dated = sorted(
        (row for row in event.rounds if row.start_date is not None),
        key=lambda row: (row.start_date, row.number),
    )
    return next((row for row in dated if (row.end_date or row.start_date) >= now), None)


def checkin_window(
    event: Season, round_: DBEventRound | None
) -> tuple[date, date | None] | None:
    """The days a check-in stands open, from `checkin_days` before it starts.

    A round gives its own window and closes when the round ends; no round
    gives the event's, which closes on the day the event starts. None is no
    window to hold anyone to: a blank `checkin_days`, or no start date.
    """
    start = round_.start_date if round_ is not None else _start(event)
    if event.checkin_days is None or start is None:
        return None
    return start - timedelta(days=event.checkin_days), (
        round_.end_date if round_ is not None else start
    )


def checkin_open(event: Season) -> bool:
    """Whether the event's check-in stands open today, in whichever shape it takes.

    An event whose next round carries dates checks in to that round; every
    other event checks in to itself, up to the day it starts. An event with
    nothing to check into is shut, and a window nobody dated never closes.
    """
    round_ = next_round(event)
    undated = any(row.start_date is None for row in event.rounds)
    if round_ is None and not undated and _start(event) is None:
        return False
    window = checkin_window(event, round_)
    if window is None:
        return True
    opens, closes = window
    now = _today()
    return opens <= now and (closes is None or now <= closes)


def _start(event: Season) -> date | None:
    """The day the event starts: its start date, or the day its time falls on."""
    return event.start_date or _day(event)


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
        claims: dict[str, Any] | None = None,
    ) -> list[EventPublic]:
        """One page of events, newest first, each with its computed phase.

        An unpublished event is a draft only an admin reads, so a caller who
        is not one sees the published rows whatever the filter asks for.
        """
        statement = select(Season).order_by(col(Season.id).desc())
        if kind is not None:
            statement = statement.where(col(Season.kind) == kind)
        if league_id is not None:
            statement = statement.where(col(Season.league_id) == league_id)
        if published is not None:
            statement = statement.where(col(Season.published).is_(published))
        if not _is_admin(claims):
            statement = statement.where(col(Season.published).is_(True))
        with Session.begin() as session:
            events = session.scalars(statement.offset(offset).limit(limit)).all()
            return _publics(session, events)

    def get(self, event_id: int, claims: dict[str, Any] | None = None) -> EventPublic:
        """One event with its stages, its divisions and how many entrants it holds.

        A draft is an admin's own, so every other caller is answered not found,
        and the qualifiers under a published event follow the same rule.
        """
        with Session.begin() as session:
            event = _event(session, event_id)
            admin = _is_admin(claims)
            if not event.published and not admin:
                raise NotFoundError(f"Event not found by id: {event_id}")
            return _public(session, event, full=True, drafts=admin)

    def add(self, data: EventCreate) -> EventPublic:
        """Create an event and the stages it plays, or one default stage.

        A body that leaves `stages` out plays one default stage. A body that
        sends an explicit empty list plays no stage at all, which is what a
        signup-only event is.
        """
        with Session.begin() as session:
            fields = data.model_dump(exclude={"stages"})
            if fields.get("entrant_kind") is None:
                fields["entrant_kind"] = _league_entrant_kind(
                    session, fields.get("league_id")
                )
            event = Season(**fields)
            session.add(event)
            session.flush()
            stages = (
                data.stages
                if "stages" in data.model_fields_set
                else [_default_stage(event)]
            )
            _write_stages(session, event, stages)
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
        holds rounds. An empty list clears them; the default stage is written
        on create only.
        """
        with Session.begin() as session:
            event = _event(session, event_id)
            rows = list(stages)
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

    def get_league(
        self, league_id: int, claims: dict[str, Any] | None = None
    ) -> LeaguePublic:
        """One league and the events that are its runs, newest first.

        A draft run reads for an admin only, as the event list does.
        """
        with Session.begin() as session:
            league = session.get(League, league_id)
            if league is None:
                raise NotFoundError(f"League not found by id: {league_id}")
            statement = (
                select(Season)
                .where(col(Season.league_id) == league_id)
                .order_by(col(Season.id).desc())
            )
            if not _is_admin(claims):
                statement = statement.where(col(Season.published).is_(True))
            events = session.scalars(statement).all()
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
        The caller's own state rides on each row: the entrant, the check-in
        shape and window, the next round and the one action the page offers.
        A caller with no id has joined nothing and reads a signup or a view.
        """
        with Session.begin() as session:
            events = session.scalars(
                select(Season)
                .where(col(Season.published).is_(True))
                .options(selectinload(rel(Season.rounds)))
                .order_by(col(Season.id).desc())
            ).all()
            joined = _joined_events(session, user_id)
            counts = series_counts_by_event(session, [event.id for event in events])
            rounds = {event.id: next_round(event) for event in events}
            hints = _round_hints(session, user_id, rounds)
            answered = _round_answers(session, user_id, rounds)
            return [
                _member_row(
                    session,
                    event,
                    counts.get(event.id, NO_SERIES),
                    event.id in joined,
                    joined.get(event.id),
                    rounds.get(event.id),
                    hints.get(event.id),
                    _answer_time(event, rounds.get(event.id), answered),
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
        """Stamp an entrant as checked in: the caller's own row, or an admin's call.

        This is the event shape of the check-in. An event whose next round
        carries dates checks in per round, through PUT /player-availability.
        """
        with Session.begin() as session:
            event = _event(session, event_id)
            if next_round(event) is not None:
                raise BadRequestError(
                    "This event checks in per round. Answer the round instead."
                )
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
        """Number the entrants 1..n inside each division and stamp the source.

        An entrant the order leaves out loses its seed, which is what seeding
        from the stage before writes: only the places that came through play.
        """
        with Session.begin() as session:
            event = _event(session, event_id)
            stage = _stage(session, event_id, stage_id)
            if stage.seeds_locked_at is not None:
                raise BadRequestError("The seeds of this stage are locked")
            rows = _live_entrants(session, event_id)
            mmrs = _mmrs(session, rows)
            order = (
                _from_previous_stage(session, event_id, stage, rows)
                if data.source is SeedSource.previous_stage
                else _seed_order(rows, mmrs, data)
            )
            taken: dict[int | None, int] = {}
            for row in order:
                taken[row.division_id] = taken.get(row.division_id, 0) + 1
                row.seed = taken[row.division_id]
                row.seed_source = data.source.value
                row.mmr_at_seed = mmrs[ident(row)]
            seeded = {ident(row) for row in order}
            for row in rows:
                if ident(row) not in seeded:
                    row.seed = None
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
    """Write the stages in the order the body gives them.

    `start` is the position of the first one, so a longer list appends. An
    empty list writes nothing; the caller decides whether a default stage
    stands in for it.
    """
    rows = list(stages)
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


def _joined_events(
    session: OrmSession, user_id: int | None
) -> dict[int, EventEntrant | None]:
    """The player's entrant row per event he joined; a GNL signup has none.

    A key with no row is a season the player signed up for, which carries no
    entrant; an event he never entered is no key at all.
    """
    if user_id is None:
        return {}
    entered = session.scalars(
        select(EventEntrant).where(
            col(EventEntrant.user_id) == user_id,
            col(EventEntrant.withdrawn_at).is_(None),
        )
    )
    joined: dict[int, EventEntrant | None] = {row.event_id: row for row in entered}
    signed = session.scalars(
        select(col(DBUserSeasonSignup.season_id)).where(
            col(DBUserSeasonSignup.user_id) == user_id
        )
    )
    for season_id in signed:
        joined.setdefault(season_id, None)
    return joined


def _round_hints(
    session: OrmSession,
    user_id: int | None,
    rounds: dict[int | None, DBEventRound | None],
) -> dict[int, AvailabilityHint]:
    """The caller's hint for the next round of every event that has one.

    The round shape stores the check-in as a round_availability row, so the
    member rows read it there and never off the entrant stamp. Only an event
    that is still running carries a next round, so this reads a few rounds.
    """
    user = session.get(User, user_id) if user_id is not None else None
    if user is None:
        return {}
    return {
        event_id: availability_hint(session, user, round_)
        for event_id, round_ in rounds.items()
        if event_id is not None and round_ is not None
    }


def _round_answers(
    session: OrmSession,
    user_id: int | None,
    rounds: dict[int | None, DBEventRound | None],
) -> dict[int, datetime | None]:
    """The events whose next round the caller has answered, and when, in one
    statement.

    The hint says whether the answer stands; this says when it was written.
    """
    wanted = {
        (event_id, round_.number)
        for event_id, round_ in rounds.items()
        if event_id is not None and round_ is not None
    }
    if user_id is None or not wanted:
        return {}
    rows = session.execute(
        select(
            col(DBRoundAvailability.season_id),
            col(DBRoundAvailability.playday),
            col(DBRoundAvailability.answered_at),
        ).where(
            col(DBRoundAvailability.user_id) == user_id,
            col(DBRoundAvailability.season_id).in_({key[0] for key in wanted}),
        )
    ).all()
    return {
        event_id: answered_at
        for event_id, playday, answered_at in rows
        if (event_id, playday) in wanted
    }


def _answer_time(
    event: Season,
    round_: DBEventRound | None,
    answered: dict[int, datetime | None],
) -> datetime | None:
    """When the caller's answer for the next round stands from.

    The row carries its own stamp; a row written before that column falls back
    to the moment the round's check-in opened.
    """
    if event.id not in answered or round_ is None:
        return None
    stamped = answered[event.id]
    if stamped is not None:
        return stamped
    window = checkin_window(event, round_)
    opens = window[0] if window else round_.start_date
    return datetime.combine(opens, time(), tzinfo=UTC) if opens else None


def _member_row(
    session: OrmSession,
    event: Season,
    counts: tuple[int, int, int],
    joined: bool,
    entrant: EventEntrant | None,
    round_: DBEventRound | None,
    hint: AvailabilityHint | None,
    answered_at: datetime | None,
) -> MemberEventRow:
    """One member home row: the event, and what the caller may do with it."""
    phase = phase_of(session, event, counts)
    is_open = event.checkin_enabled and checkin_open(event)
    shape = (
        None
        if not event.checkin_enabled
        else "round"
        if round_ is not None
        else "event"
    )
    if shape != "round":
        hint = None
    answered = hint in ("answered_yes", "answered_no")
    # The round shape takes its check-in through PUT /player-availability
    checked_in_at = (
        (answered_at if answered else None)
        if shape == "round" and round_ is not None
        else (entrant.checked_in_at if entrant else None)
    )
    return MemberEventRow(
        kind=event.kind,
        id=ident(event),
        name=event.name,
        league_short_name=event.league_short_name,
        start=_start(event),
        end=event.end_date,
        phase=phase,
        signups_open=event.signups_open,
        joined=joined,
        url=event.page_url,
        entrant_id=ident(entrant) if entrant else None,
        checked_in_at=checked_in_at,
        checkin_shape=shape,
        checkin_open=is_open,
        next_round=EventRoundPublic.from_row(round_) if round_ else None,
        availability_hint=hint,
        action=_member_action(phase, event, joined, checked_in_at, is_open),
    )


def _member_action(
    phase: EventPhase,
    event: Season,
    joined: bool,
    checked_in_at: datetime | None,
    checkin_open_now: bool,
) -> MemberAction:
    """The one action the member home offers, so every page agrees on it."""
    if phase in ("running", "finished"):
        return "view"
    if joined:
        if checked_in_at is not None:
            return "checked_in"
        return "check_in" if checkin_open_now else "withdraw"
    return "sign_up" if event.signups_open else "closed"


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
    drafts: bool = True,
) -> EventPublic:
    """One event payload; the stages, the divisions and the entrant count only
    when it is the subject of the read. `drafts` false leaves the unpublished
    qualifiers out for a caller who is not an admin.
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
    children = (
        select(Season)
        .where(col(Season.parent_id) == event.id)
        .order_by(col(Season.id).desc())
    )
    if not drafts:
        children = children.where(col(Season.published).is_(True))
    public.children = [
        EventPublic.model_validate(row) for row in session.scalars(children)
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


def _signup_race(data: EntrantSignup) -> Race:
    """The race a player row signs up on; one player plays one race."""
    if data.race is None:
        raise BadRequestError("Name the race you sign up on")
    return data.race


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


def _w3c_season(session: OrmSession) -> int:
    """The W3C season the app reads ratings against, or the newest one stored."""
    named = session.scalar(
        select(col(Settings.value)).where(col(Settings.key) == W3C_SEASON_KEY)
    )
    if named:
        return int(named)
    return session.scalar(select(func.max(col(W3CStats.wc3_season)))) or 0


def _stats_for(user: User, race: Race | None, season: int) -> tuple[int | None, int]:
    """The player's current W3C rating on that race, and the games behind it.

    A season the player did not play on that race carries no rating, so the
    rating is the newest stored season that carries one, three seasons back
    from the season the app is on and no further: an older rating is not the
    player's current one. The games are every season the app has synced for
    that race, because a min-games rule asks how much the player has played,
    not how much this season.
    """
    rows = [stat for stat in (user.w3c_stats or []) if stat.race == race]
    played = [stat for stat in rows if stat.mmr and stat.wc3_season > season - SEASONS]
    rating = max(played, key=lambda stat: stat.wc3_season).mmr if played else None
    return rating, sum(stat.games or 0 for stat in rows)


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

    Three reads fill every row: the players with their W3C stats, the teams,
    and the rosters the rating of a team entrant is the mean of.
    """
    team_ids = {row.team_id for row in rows if row.team_id}
    users = _users_for(session, rows)
    teams = {
        team.id: team
        for team in session.scalars(select(Team).where(col(Team.id).in_(team_ids)))
    }
    season = _w3c_season(session)
    means = _team_mmrs(session, rows, season)
    return [_entrant_public(event, row, users, teams, means, season) for row in rows]


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
    """Each entrant against the rating of the race it signed up on.

    A team answers the mean of its roster, so a division cut and a seed order
    read one number for every entrant, whoever stands behind it.
    """
    users = _users_for(session, rows)
    season = _w3c_season(session)
    teams = _team_mmrs(session, rows, season)
    return {ident(row): _entrant_mmr(row, users, teams, season) for row in rows}


def _entrant_mmr(
    row: EventEntrant,
    users: dict[int | None, User],
    teams: dict[int, int | None],
    season: int,
) -> int | None:
    """The rating of one entrant: the team mean, or the player on its signup race."""
    if row.team_id is not None:
        return teams.get(row.team_id)
    if row.user_id not in users:
        return None
    return _stats_for(users[row.user_id], row.race, season)[0]


def _team_mmrs(
    session: OrmSession, rows: Sequence[EventEntrant], season: int
) -> dict[int, int | None]:
    """Every team entrant against the mean rating of its live roster.

    Two reads answer the whole list, never one per team: the rosters through
    user_team_season against the event the team entered, and the races those
    members signed up on. A member is rated the way a solo entrant is, on his
    signup race or on the race his profile names when he made no signup, and
    a team no member of which is rated answers None, as an unrated player does.
    """
    teams = {row.team_id for row in rows if row.team_id is not None}
    if not teams:
        return {}
    events = {row.event_id for row in rows if row.team_id is not None}
    members = session.scalars(
        select(DBUserTeamSeason)
        .options(
            selectinload(rel(DBUserTeamSeason.user)).selectinload(rel(User.w3c_stats))
        )
        .where(
            col(DBUserTeamSeason.team_id).in_(teams),
            col(DBUserTeamSeason.season_id).in_(events),
        )
    ).all()
    races = {
        user_id: race
        for user_id, race in session.execute(
            select(col(DBUserSeasonSignup.user_id), col(DBUserSeasonSignup.race)).where(
                col(DBUserSeasonSignup.season_id).in_(events),
                col(DBUserSeasonSignup.user_id).in_(
                    {member.user_id for member in members}
                ),
            )
        ).all()
    }
    rated: dict[int, list[int]] = {team_id: [] for team_id in teams}
    for member in members:
        race = races.get(member.user_id) or member.user.race
        mmr = _stats_for(member.user, race, season)[0]
        if mmr is not None:
            rated[member.team_id].append(mmr)
    return {
        team_id: round(sum(mmrs) / len(mmrs)) if mmrs else None
        for team_id, mmrs in rated.items()
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

    A qualifier seeds from the entrant list of a parent event, which is not
    wired yet, so it refuses with `not_built`. An entrant the order list
    leaves out follows on MMR.
    """
    if data.source is SeedSource.qualifier:
        raise ApiError(
            400,
            {
                "error": "not_built",
                "message": "Seeding from a qualifier waits on the parent event",
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


def _from_previous_stage(
    session: OrmSession,
    event_id: int,
    stage: EventStage,
    rows: Sequence[EventEntrant],
) -> list[EventEntrant]:
    """The entrants the stage before sends on, in the order `advance` seeds them.

    The order is the standings of that stage, top `advance_count` places per
    division, so a playoff seeded by hand and one seeded by `advance` read the
    same. Nothing is generated here.
    """
    before = stage_engine.previous_stage(session, event_id, stage)
    if before is None:
        raise BadRequestError("This stage is the first one of the event")
    by_id = {ident(row): row for row in rows}
    return [
        by_id[entrant_id]
        for division in stage_engine.advancing(session, event_id, before)
        for entrant_id in division
        if entrant_id in by_id
    ]


def _entrant_public(
    event: Season,
    row: EventEntrant,
    users: dict[int | None, User],
    teams: dict[int | None, Team],
    means: dict[int, int | None],
    season: int,
) -> EventEntrantPublic:
    """One entrant payload: the identity, the rating it is seeded on, the warnings."""
    user = users.get(row.user_id)
    team = teams.get(row.team_id)
    mmr, games = _stats_for(user, row.race, season) if user else (None, 0)
    if row.team_id is not None:
        mmr = means.get(row.team_id)
    return EventEntrantPublic(
        id=ident(row),
        event_id=row.event_id,
        user=UserPublic.from_user(user) if user else None,
        team=TeamReduced.from_team(team) if team else None,
        race=row.race,
        note=row.note,
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
        return _by_battle_tag(session, data.battle_tag, _signup_race(data))
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
        return _by_battle_tag(session, data.battle_tag, _signup_race(data))
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
        raise BadRequestError("A GNL season takes its signups on its season page")
    # A player plays one race; a team fields the races of its roster
    race = data.race if team_id is not None else _signup_race(data)
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
        existing.race = race
        existing.note = data.note
        existing.channel = data.channel
        session.flush()
        return existing
    row = EventEntrant(
        event_id=ident(event),
        user_id=user_id,
        team_id=team_id,
        race=race,
        note=data.note,
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
