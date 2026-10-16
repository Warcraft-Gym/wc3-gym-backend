"""A cup played over several rounds: its legs, their check-ins and the overall table.

A cup made with rounds writes one leg per round, each with its own copy of the
cup's stages, so every round is drawn, played and placed on its own. A round
draws the players checked in for it. A runner finishes a round once it is
played: its places pay points from the cup's points table, and the seeds are
cleared so the next round seeds afresh. The overall table adds up the points
of every finished round; a tie breaks on the best single place, then on more
of that place. Finishing the cup pays its awards from the overall table.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.checkin_hint import checkin_refusal, checkin_window
from app.core.db import Session
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.core.outcome import scored
from app.models.base import ident
from app.models.cup_overall import CupOverallPublic, OverallLeg, OverallRow
from app.models.cup_rounds import (
    CupLeg,
    CupLegCheckin,
    CupLegPublic,
    CupLegStage,
    CupLegUpdate,
    CupLegWrite,
)
from app.models.cup_series import CupSeries
from app.models.cup_settings import CupSettings
from app.models.enums import EventKind
from app.models.event_entrant import EventEntrant
from app.models.event_stage import EventStage, EventStageWrite
from app.models.relationships import DBEventRound
from app.models.season import Season
from app.models.types import utcnow
from app.models.user import User, UserSummaryPublic
from app.services import cup_reads, organizers

# What each place of a round pays when the cup names no table of its own
DEFAULT_POINTS = [10, 8, 6, 5, 4, 3, 2, 1]


def points_of(text: str | None) -> list[int]:
    """The points table of a cup, best place first."""
    if not text:
        return list(DEFAULT_POINTS)
    return [int(word) for word in text.split(",") if word.strip()]


def points_text(points: Sequence[int] | None) -> str | None:
    """A points table as the settings row stores it; null keeps the default."""
    if not points:
        return None
    if any(value < 0 for value in points):
        raise BadRequestError("A place pays no fewer than 0 points")
    return ",".join(str(value) for value in points)


def write_legs(
    session: OrmSession,
    event: Season,
    legs: Sequence[CupLegWrite],
    stages: Sequence[EventStageWrite],
) -> None:
    """One leg per round, each with its own copy of the cup's stages; the
    stage positions run on through the rounds, so the event reads in order."""
    if len(legs) < 2:
        raise BadRequestError("A cup played over rounds plays two rounds or more")
    if not stages:
        raise BadRequestError("A round plays the cup's stages, so it needs one")
    position = 1
    for number, leg in enumerate(legs, start=1):
        row = CupLeg(
            event_id=ident(event),
            number=number,
            name=leg.name or f"Round {number}",
            starts_at=leg.starts_at,
        )
        session.add(row)
        session.flush()
        for stage in stages:
            copy = EventStage(
                event_id=ident(event), position=position, **stage.model_dump()
            )
            session.add(copy)
            session.flush()
            session.add(CupLegStage(stage_id=ident(copy), leg_id=ident(row)))
            position += 1
    session.flush()


def set_leg_stages(
    session: OrmSession, event_id: int, rows: Sequence[EventStageWrite]
) -> None:
    """Write the format of a cup played over rounds. A body of one round's
    stages is written onto every round, so the rounds keep playing the same
    format; a body of every stage is written in place. The rounds keep their
    number of stages either way."""
    stages = list(
        session.scalars(
            select(EventStage)
            .join(CupLegStage, col(CupLegStage.stage_id) == col(EventStage.id))
            .where(col(EventStage.event_id) == event_id)
            .order_by(col(EventStage.position))
        )
    )
    legs = len(legs_of(session, event_id))
    per_leg = len(stages) // legs
    if len(rows) == per_leg:
        rows = [row for _ in range(legs) for row in rows]
    if len(rows) != len(stages):
        raise BadRequestError(
            "Every round of this cup plays the same stages; change their format, not their number"
        )
    for stage, row in zip(stages, rows, strict=True):
        stage.sqlmodel_update(row.model_dump())
    session.flush()


def leg_field(
    session: OrmSession, stage: EventStage, rows: Sequence[EventEntrant]
) -> list[EventEntrant]:
    """The entrants a stage seeds: on a stage of a round, the ones checked in
    for that round; on any other stage, every one of `rows`."""
    leg = session.get(CupLegStage, ident(stage))
    if leg is None:
        return list(rows)
    checked = set(
        session.scalars(
            select(col(CupLegCheckin.entrant_id)).where(
                col(CupLegCheckin.leg_id) == leg.leg_id
            )
        )
    )
    return [row for row in rows if ident(row) in checked]


def hold_unfinished(session: OrmSession, stage: EventStage) -> None:
    """Refuse to take back the draw of a finished round; its places count."""
    leg_stage = session.get(CupLegStage, ident(stage))
    leg = session.get(CupLeg, leg_stage.leg_id) if leg_stage is not None else None
    if leg is not None and leg.finished_at is not None:
        raise BadRequestError(
            "This round is finished; reopen it before its draw is undone"
        )


def has_legs(session: OrmSession, event_id: int) -> bool:
    return (
        session.scalar(
            select(col(CupLeg.id)).where(col(CupLeg.event_id) == event_id).limit(1)
        )
        is not None
    )


def legs_of(session: OrmSession, event_id: int) -> list[CupLegPublic]:
    """Every round of the cup in order, with its stages, its check-ins and its
    check-in window."""
    legs = session.scalars(
        select(CupLeg)
        .where(col(CupLeg.event_id) == event_id)
        .order_by(col(CupLeg.number))
    ).all()
    event = session.get(Season, event_id)
    if not legs or event is None:
        return []
    ids = [ident(leg) for leg in legs]
    stages: dict[int, list[tuple[int, int]]] = {}
    for stage_id, leg_id, position in session.execute(
        select(
            col(CupLegStage.stage_id), col(CupLegStage.leg_id), col(EventStage.position)
        )
        .join(EventStage, col(EventStage.id) == col(CupLegStage.stage_id))
        .where(col(CupLegStage.leg_id).in_(ids))
    ):
        stages.setdefault(leg_id, []).append((position, stage_id))
    checked: dict[int, list[int]] = {}
    for leg_id, entrant_id in session.execute(
        select(col(CupLegCheckin.leg_id), col(CupLegCheckin.entrant_id))
        .where(col(CupLegCheckin.leg_id).in_(ids))
        .order_by(col(CupLegCheckin.checked_in_at))
    ):
        checked.setdefault(leg_id, []).append(entrant_id)
    windows = {ident(leg): checkin_window(event, leg) for leg in legs}
    return [
        CupLegPublic(
            id=ident(leg),
            number=leg.number,
            name=leg.name,
            starts_at=leg.starts_at,
            finished_at=leg.finished_at,
            stage_ids=[stage_id for _, stage_id in sorted(stages.get(ident(leg), []))],
            checked_in=checked.get(ident(leg), []),
            checkin_opens_at=windows[ident(leg)].opens,
            checkin_closes_at=windows[ident(leg)].closes,
        )
        for leg in legs
    ]


def check_in(
    event_id: int,
    leg_id: int,
    entrant_id: int | None,
    claims: dict[str, Any] | None,
    present: bool,
) -> list[CupLegPublic]:
    """Check a player in for one round, or out again, while the round is not
    drawn. A player checks their own entry in, inside the round's window; a
    runner checks in anyone at any time before the draw."""
    with Session.begin() as session:
        event = _cup(session, event_id)
        leg = _leg(session, event_id, leg_id)
        if leg.finished_at is not None or leg_drawn(session, ident(leg)):
            raise BadRequestError("This round is drawn; its players are set")
        runs = organizers.runs_in(session, claims, event_id)
        entrant = _entrant_for(session, event, entrant_id, claims, runs)
        refusal = checkin_refusal(
            checkin_window(event, leg),
            utcnow(),
            event.early_checkin,
            False,
            f"Check-in for {leg.name or f'round {leg.number}'}",
        )
        if refusal is not None and not runs:
            raise ApiError(403, {"error": "checkin_closed", "message": refusal})
        row = session.get(CupLegCheckin, (ident(leg), ident(entrant)))
        if present and row is None:
            cup_reads.hold_complete_team(session, event, entrant)
            session.add(
                CupLegCheckin(
                    leg_id=ident(leg), entrant_id=ident(entrant), checked_in_at=utcnow()
                )
            )
        elif not present and row is not None:
            session.delete(row)
        session.flush()
        return legs_of(session, event_id)


def check_in_everyone(event_id: int, leg_id: int) -> list[CupLegPublic]:
    """A runner checks every playing entrant in for one round; a cup team
    still waiting for a player is left out."""
    with Session.begin() as session:
        event = _cup(session, event_id)
        leg = _leg(session, event_id, leg_id)
        if leg.finished_at is not None or leg_drawn(session, ident(leg)):
            raise BadRequestError("This round is drawn; its players are set")
        held = set(
            session.scalars(
                select(col(CupLegCheckin.entrant_id)).where(
                    col(CupLegCheckin.leg_id) == ident(leg)
                )
            )
        )
        now = utcnow()
        playing = _playing(session, event_id)
        players = cup_reads.team_players(
            session, [row.cup_team_id for row in playing if row.cup_team_id]
        )
        for entrant in playing:
            team_id = entrant.cup_team_id
            if (
                event.team_size
                and team_id
                and players.get(team_id, 0) < event.team_size
            ):
                continue
            if ident(entrant) not in held:
                session.add(
                    CupLegCheckin(
                        leg_id=ident(leg), entrant_id=ident(entrant), checked_in_at=now
                    )
                )
        session.flush()
        return legs_of(session, event_id)


def finish_leg(event_id: int, leg_id: int) -> list[CupLegPublic]:
    """Close a played round: its places count from now on, and the seeds go,
    so the next round seeds afresh from the players checked in for it."""
    with Session.begin() as session:
        _cup(session, event_id)
        leg = _leg(session, event_id, leg_id)
        if leg.finished_at is not None:
            raise BadRequestError("This round is finished already")
        series = session.scalars(
            select(CupSeries)
            .join(DBEventRound, col(DBEventRound.id) == col(CupSeries.round_id))
            .join(CupLegStage, col(CupLegStage.stage_id) == col(DBEventRound.stage_id))
            .where(col(CupLegStage.leg_id) == ident(leg))
        ).all()
        if not series or any(not scored(row) for row in series):
            raise BadRequestError("Every series of the round needs a result first")
        leg.finished_at = utcnow()
        session.execute(
            update(EventEntrant)
            .where(col(EventEntrant.event_id) == event_id)
            .values(seed=None, seed_source=None, mmr_at_seed=None)
        )
        session.flush()
        return legs_of(session, event_id)


def reopen_leg(event_id: int, leg_id: int) -> list[CupLegPublic]:
    """Take a round's finish back while the cup is open; its points stop counting."""
    with Session.begin() as session:
        event = _cup(session, event_id)
        if event.closed_at is not None:
            raise BadRequestError("The cup is finished; reopen it first")
        leg = _leg(session, event_id, leg_id)
        leg.finished_at = None
        session.flush()
        return legs_of(session, event_id)


def update_leg(event_id: int, leg_id: int, data: CupLegUpdate) -> list[CupLegPublic]:
    """Rename a round or move its start, while the cup is open. A round starts
    after the one before it and before the one after; the first round's start
    is the cup's start."""
    with Session.begin() as session:
        event = _open_cup(session, event_id)
        leg = _leg(session, event_id, leg_id)
        changes = data.model_dump(exclude_unset=True)
        if "name" in changes:
            leg.name = (changes["name"] or "").strip() or f"Round {leg.number}"
        if "starts_at" in changes:
            _hold_order(session, event_id, leg.number, changes["starts_at"])
            leg.starts_at = changes["starts_at"]
            if leg.number == 1:
                _start_cup(event, leg.starts_at)
        session.flush()
        return legs_of(session, event_id)


def add_leg(event_id: int, data: CupLegWrite) -> list[CupLegPublic]:
    """Add a round after the last one, playing the same stages as the others."""
    with Session.begin() as session:
        _open_cup(session, event_id)
        legs = _rows(session, event_id)
        if not legs:
            raise BadRequestError("This cup is played on one evening; it has no rounds")
        last = legs[-1]
        number = last.number + 1
        _hold_order(session, event_id, number, data.starts_at)
        stages = _stages_of(session, ident(last))
        position = (
            session.scalar(
                select(func.max(col(EventStage.position))).where(
                    col(EventStage.event_id) == event_id
                )
            )
            or 0
        )
        leg = CupLeg(
            event_id=event_id,
            number=number,
            name=(data.name or "").strip() or f"Round {number}",
            starts_at=data.starts_at,
        )
        session.add(leg)
        session.flush()
        for stage in stages:
            position += 1
            copy = EventStage(
                event_id=event_id,
                position=position,
                **EventStageWrite.model_validate(
                    stage, from_attributes=True
                ).model_dump(),
            )
            session.add(copy)
            session.flush()
            session.add(CupLegStage(stage_id=ident(copy), leg_id=ident(leg)))
        session.flush()
        return legs_of(session, event_id)


def remove_leg(event_id: int, leg_id: int) -> list[CupLegPublic]:
    """Remove a round that is not drawn, with its stages and its check-ins; the
    rounds after it move up a number, and a cup keeps two rounds or more."""
    with Session.begin() as session:
        event = _open_cup(session, event_id)
        leg = _leg(session, event_id, leg_id)
        legs = _rows(session, event_id)
        if len(legs) <= 2:
            raise BadRequestError("A cup over rounds keeps two rounds or more")
        if leg.finished_at is not None or leg_drawn(session, ident(leg)):
            raise BadRequestError(
                f"Round {leg.number} is drawn; undo its draw before it goes"
            )
        for stage in _stages_of(session, ident(leg)):
            session.delete(stage)
        session.delete(leg)
        session.flush()
        for later in legs:
            if later.number > leg.number:
                if later.name == f"Round {later.number}":
                    later.name = f"Round {later.number - 1}"
                later.number -= 1
        # the stage positions close up, so the event still reads its stages in order
        for position, stage in enumerate(
            session.scalars(
                select(EventStage)
                .where(col(EventStage.event_id) == event_id)
                .order_by(col(EventStage.position))
            ),
            start=1,
        ):
            stage.position = position
        session.flush()
        if leg.number == 1:
            first = _rows(session, event_id)[0]
            _start_cup(event, first.starts_at)
        session.flush()
        return legs_of(session, event_id)


def follow_start(session: OrmSession, event: Season) -> None:
    """A cup over rounds whose start moved moves its first round with it."""
    legs = _rows(session, ident(event))
    if legs:
        legs[0].starts_at = event.starts_at


def overall(event_id: int) -> CupOverallPublic:
    """The cup's overall table over its finished rounds."""
    with Session.begin() as session:
        _cup(session, event_id)
        settings = session.get(CupSettings, event_id)
        return CupOverallPublic(
            points_by_place=points_of(settings.points_by_place if settings else None),
            legs=legs_of(session, event_id),
            rows=overall_rows(session, event_id),
        )


def overall_rows(session: OrmSession, event_id: int) -> list[OverallRow]:
    """Every playing entrant with the points each finished round paid it.

    The points add up, a tie breaks on the best single place and then on more
    of that place, and entrants still level share their position.
    """
    from app.services.awards import event_places

    settings = session.get(CupSettings, event_id)
    table = points_of(settings.points_by_place if settings else None)
    legs = [leg for leg in legs_of(session, event_id) if leg.finished_at is not None]
    results: dict[int, list[OverallLeg]] = {}
    for leg in legs:
        for place, line in event_places(session, event_id, leg.stage_ids):
            paid = table[place - 1] if place <= len(table) else 0
            results.setdefault(line.entrant_id, []).append(
                OverallLeg(leg_id=leg.id, place=place, points=paid)
            )
    entrants = {ident(row): row for row in _playing(session, event_id)}
    for entrant_id in results:
        if entrant_id not in entrants:
            found = session.get(EventEntrant, entrant_id)
            if found is not None:
                entrants[entrant_id] = found
    names = _names(session, list(entrants.values()))
    rows = []
    for entrant_id in entrants:
        played = results.get(entrant_id, [])
        best = min((one.place for one in played), default=None)
        rows.append(
            (
                -sum(one.points for one in played),
                best if best is not None else 10**6,
                -sum(1 for one in played if one.place == best),
                names[entrant_id][0] or "",
                entrant_id,
                played,
                best,
            )
        )
    rows.sort()
    answer: list[OverallRow] = []
    for index, (points, best_key, best_count, _, entrant_id, played, best) in enumerate(
        rows
    ):
        level = index and rows[index - 1][:3] == (points, best_key, best_count)
        name, user = names[entrant_id]
        answer.append(
            OverallRow(
                position=answer[-1].position if level else index + 1,
                entrant_id=entrant_id,
                name=name,
                user=user,
                team_id=entrants[entrant_id].cup_team_id,
                points=-points,
                best=best,
                legs=played,
            )
        )
    return answer


def _names(
    session: OrmSession, entrants: Sequence[EventEntrant]
) -> dict[int, tuple[str | None, UserSummaryPublic | None]]:
    """The name of every entrant, the player or the cup team, and the player."""
    from app.models.cup_team import CupTeam

    users = {
        ident(user): user
        for user in session.scalars(
            select(User).where(
                col(User.id).in_({row.user_id for row in entrants if row.user_id})
            )
        )
    }
    teams = {
        ident(team): team.name
        for team in session.scalars(
            select(CupTeam).where(
                col(CupTeam.id).in_(
                    {row.cup_team_id for row in entrants if row.cup_team_id}
                )
            )
        )
    }
    found: dict[int, tuple[str | None, UserSummaryPublic | None]] = {}
    for row in entrants:
        user = users.get(row.user_id) if row.user_id else None
        found[ident(row)] = (
            teams.get(row.cup_team_id)
            if row.cup_team_id
            else (user.name if user else None),
            UserSummaryPublic.from_user(user) if user else None,
        )
    return found


def _cup(session: OrmSession, event_id: int) -> Season:
    event = session.get(Season, event_id)
    if event is None:
        raise NotFoundError(f"Event not found by id: {event_id}")
    if event.kind is not EventKind.cup:
        raise BadRequestError("Only a cup plays rounds")
    return event


def _open_cup(session: OrmSession, event_id: int) -> Season:
    event = _cup(session, event_id)
    if event.closed_at is not None or event.cancelled_at is not None:
        raise BadRequestError("The cup is over; its rounds stay as they are")
    return event


def _rows(session: OrmSession, event_id: int) -> list[CupLeg]:
    return list(
        session.scalars(
            select(CupLeg)
            .where(col(CupLeg.event_id) == event_id)
            .order_by(col(CupLeg.number))
        )
    )


def _stages_of(session: OrmSession, leg_id: int) -> list[EventStage]:
    return list(
        session.scalars(
            select(EventStage)
            .join(CupLegStage, col(CupLegStage.stage_id) == col(EventStage.id))
            .where(col(CupLegStage.leg_id) == leg_id)
            .order_by(col(EventStage.position))
        )
    )


def _hold_order(
    session: OrmSession, event_id: int, number: int, starts_at: datetime | None
) -> None:
    """Refuse a start that puts round `number` before the round ahead of it or
    after the round behind it."""
    if starts_at is None:
        return
    for other in _rows(session, event_id):
        if other.starts_at is None or other.number == number:
            continue
        if other.number < number and starts_at <= other.starts_at:
            raise BadRequestError(f"Round {number} starts after round {other.number}")
        if other.number > number and starts_at >= other.starts_at:
            raise BadRequestError(f"Round {number} starts before round {other.number}")


def _start_cup(event: Season, starts_at: datetime | None) -> None:
    """The first round's start is the cup's start."""
    event.starts_at = starts_at
    event.start_date = starts_at.date() if starts_at is not None else event.start_date


def _leg(session: OrmSession, event_id: int, leg_id: int) -> CupLeg:
    leg = session.get(CupLeg, leg_id)
    if leg is None or leg.event_id != event_id:
        raise NotFoundError(f"Round not found by id: {leg_id}")
    return leg


def leg_drawn(session: OrmSession, leg_id: int) -> bool:
    return (
        session.scalar(
            select(col(CupSeries.id))
            .join(DBEventRound, col(DBEventRound.id) == col(CupSeries.round_id))
            .join(CupLegStage, col(CupLegStage.stage_id) == col(DBEventRound.stage_id))
            .where(col(CupLegStage.leg_id) == leg_id)
            .limit(1)
        )
        is not None
    )


def _playing(session: OrmSession, event_id: int) -> list[EventEntrant]:
    return list(
        session.scalars(
            select(EventEntrant)
            .where(
                col(EventEntrant.event_id) == event_id,
                col(EventEntrant.withdrawn_at).is_(None),
                col(EventEntrant.waitlisted_at).is_(None),
            )
            .order_by(col(EventEntrant.id))
        )
    )


def _entrant_for(
    session: OrmSession,
    event: Season,
    entrant_id: int | None,
    claims: dict[str, Any] | None,
    runs: bool,
) -> EventEntrant:
    """The entry a check-in is for: one a runner names, or the caller's own."""
    if entrant_id is not None:
        entrant = session.get(EventEntrant, entrant_id)
        if entrant is None or entrant.event_id != ident(event):
            raise NotFoundError(f"Entrant not found by id: {entrant_id}")
        if runs or _owns(session, entrant, claims):
            return entrant
        raise ApiError(403, {"error": "Check in your own entry"})
    for entrant in _playing(session, ident(event)):
        if _owns(session, entrant, claims):
            return entrant
    raise BadRequestError("You are not signed up for this cup")


def _owns(
    session: OrmSession, entrant: EventEntrant, claims: dict[str, Any] | None
) -> bool:
    """Whether the caller plays this entry: its player, or a member of its cup team."""
    from app.models.cup_team import CupTeamMember

    sub = (claims or {}).get("sub")
    user_id = (
        session.scalar(select(col(User.id)).where(col(User.discordId) == str(sub)))
        if sub
        else None
    )
    if user_id is None:
        return False
    if entrant.user_id == user_id:
        return True
    return (
        entrant.cup_team_id is not None
        and session.get(CupTeamMember, (entrant.cup_team_id, user_id)) is not None
    )
