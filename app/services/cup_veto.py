"""The map veto of a cup series, step by step.

The board is derived: the cup's order (by best-of, or its pick_ban list)
names every step and its side, the cup's pool names the maps, and a fixed
rule takes the round's map off the board because it is already game 1. Only
the steps taken are stored, in `cup_veto_step`.

A runner reads and edits every board; a player reads the board of a series
one of their sides plays, and takes the steps of that side.
"""

from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col, select

from app.core.exceptions import BadRequestError
from app.core.map_order import cup_order, rules_of
from app.core.outcome import stands_on_side
from app.models.base import ident
from app.models.cup_series import CupSeries, CupVetoStep
from app.models.cup_team import CupTeam, CupTeamMember
from app.models.event_entrant import EventEntrant
from app.models.map import Map
from app.models.relationships import DBEventRound
from app.models.series_veto_step import (
    SeriesVetoPublic,
    SeriesVetoStepPublic,
    VetoPlayer,
)
from app.models.user import User
from app.services.cup_reads import CupRules, acts_for_side, event_of
from app.services.cup_reads import rules_of as cup_rules_of
from app.services.series_veto import order_of

NOT_YOURS = "The last step is not yours to take back"


def is_complete(session: OrmSession, series: CupSeries) -> bool:
    """Whether every step of the series' order is taken. An order with no
    steps has nothing to take."""
    return len(steps_of(session, ident(series))) >= len(_order(session, series))


def board(
    session: OrmSession, series: CupSeries, player_id: int | None
) -> SeriesVetoPublic:
    """The board as one player sees it: their side and their turn. A runner
    who plays neither side reads it with no side of their own."""
    if stands_on_side(series, 1) is None or stands_on_side(series, 2) is None:
        raise BadRequestError("The series has no sides to veto with yet")
    rules = cup_rules_of(session, series)
    order = _order(session, series)
    steps = steps_of(session, ident(series))
    side = _letter(acts_for_side(session, series, player_id))
    complete = len(steps) >= len(order)
    return SeriesVetoPublic(
        steps=[
            SeriesVetoStepPublic(
                step_no=step.step_no,
                side=step.side,
                action=step.action,
                map_id=step.map_id,
                entered_by=step.entered_by,
                shortname=played.shortname if played else None,
                name=played.name if played else None,
            )
            for step in steps
            for played in (session.get(Map, step.map_id),)
        ],
        order=order,
        viewer_side=side,
        on_turn=side is not None and not complete and _side(order[len(steps)]) == side,
        complete=complete,
        pool=rules.map_pool,
        week_map_id=_fixed_map_id(session, series, rules),
        map_rules=rules.map_rules,
        player1=_veto_side(session, series, 1),
        player2=_veto_side(session, series, 2),
    )


def take(
    session: OrmSession,
    series: CupSeries,
    player_id: int | None,
    action: str,
    map_id: int | None,
    runner: bool,
) -> None:
    """Take the step the order names next, record it for whichever side the
    order names when the veto happened elsewhere, or take back the last step.

    A player takes their own side's steps and takes back what they entered; a
    runner records any step and takes back any last step.
    """
    steps = steps_of(session, ident(series))
    side = _letter(acts_for_side(session, series, player_id))
    if action == "undo":
        # A forced last step goes with the step that forced it: nobody took it
        undone = steps[-2:] if _forced_last(session, series, steps) else steps[-1:]
        if not undone:
            raise BadRequestError(NOT_YOURS)
        own = player_id == undone[0].entered_by or side == undone[0].side
        if not runner and not own:
            raise BadRequestError(NOT_YOURS)
        for step in undone:
            session.delete(step)
    else:
        named = None if action == "record" or runner and side is None else side
        _take_step(session, series, steps, named, map_id, player_id)
    session.flush()


def steps_of(session: OrmSession, series_id: int) -> list[CupVetoStep]:
    return list(
        session.scalars(
            select(CupVetoStep)
            .where(col(CupVetoStep.series_id) == series_id)
            .order_by(col(CupVetoStep.step_no))
        )
    )


def _order(session: OrmSession, series: CupSeries) -> list[str]:
    """The steps one series plays: its own by its best-of when the cup vetoes
    that way, else the cup's pick_ban list."""
    event = event_of(session, series)
    if event.veto_by_best_of:
        rules = cup_rules_of(session, series)
        return cup_order(rules.best_of, len(rules.map_pool))
    return order_of(event)


def _side(entry: str) -> str:
    return entry.rsplit("_", 1)[-1].upper()


def _letter(side: int | None) -> str | None:
    """The side as the board spells it: A for the front side, B for the other."""
    return None if side is None else ("A" if side == 1 else "B")


def _fixed_map_id(
    session: OrmSession, series: CupSeries, rules: CupRules
) -> int | None:
    """The map a fixed rule claims for game 1; it never enters the veto."""
    if "fixed" not in rules_of(rules.map_rules):
        return None
    row = session.get(DBEventRound, series.round_id)
    return row.map_id if row else None


def _take_step(
    session: OrmSession,
    series: CupSeries,
    steps: list[CupVetoStep],
    side: str | None,
    map_id: int | None,
    entered_by: int | None,
) -> None:
    """A null side records the step for whichever side the order names next."""
    rules = cup_rules_of(session, series)
    order = _order(session, series)
    if len(steps) >= len(order):
        raise BadRequestError("The veto is complete")
    if side is not None and _side(order[len(steps)]) != side:
        raise BadRequestError("It is not your turn")
    if map_id is None or map_id not in set(rules.map_pool):
        raise BadRequestError(f"Map not part of the cup's pool, map id: {map_id}")
    if map_id in {step.map_id for step in steps}:
        raise BadRequestError(f"Map already used, map id: {map_id}")
    fixed = _fixed_map_id(session, series, rules)
    if map_id == fixed:
        raise BadRequestError(f"Map played as game 1, map id: {map_id}")
    session.add(
        CupVetoStep(
            series_id=ident(series),
            step_no=len(steps) + 1,
            side=_side(order[len(steps)]),
            # The order names the action; the client only names the map
            action=order[len(steps)].split("_")[0].lower(),
            map_id=map_id,
            entered_by=entered_by,
        )
    )
    # The final step takes itself when one entry and one map remain: no choice is left
    taken = {step.map_id for step in steps} | {map_id}
    left = [one for one in rules.map_pool if one not in taken and one != fixed]
    if len(order) - len(steps) == 2 and len(left) == 1:
        session.add(
            CupVetoStep(
                series_id=ident(series),
                step_no=len(steps) + 2,
                side=_side(order[-1]),
                action=order[-1].split("_")[0].lower(),
                map_id=left[0],
            )
        )


def _forced_last(
    session: OrmSession, series: CupSeries, steps: list[CupVetoStep]
) -> bool:
    """Whether the last step took itself: the order is complete and it used up
    the whole board, so one map was left for it."""
    rules = cup_rules_of(session, series)
    order = _order(session, series)
    fixed = _fixed_map_id(session, series, rules)
    return len(order) >= 2 and len(steps) == len(order) == len(rules.map_pool) - (
        fixed is not None
    )


def _veto_side(session: OrmSession, series: CupSeries, side: int) -> VetoPlayer:
    """The name the board prints for one side: the player, or the cup team.

    `id` is the user of the side or nothing at all, so a client may compare it
    with its own user id; a team side names the team and lists its players,
    so a step any of them enters reads as the side's own.
    """
    user_id = series.player1_id if side == 1 else series.player2_id
    user = session.get(User, user_id) if user_id else None
    if user is not None:
        return VetoPlayer(id=ident(user), name=user.name)
    entrant_id = series.entrant1_id if side == 1 else series.entrant2_id
    entrant = session.get(EventEntrant, entrant_id) if entrant_id else None
    team = (
        session.get(CupTeam, entrant.cup_team_id)
        if entrant and entrant.cup_team_id
        else None
    )
    if team is None:
        return VetoPlayer()
    members = session.scalars(
        select(col(CupTeamMember.user_id)).where(
            col(CupTeamMember.team_id) == ident(team)
        )
    ).all()
    return VetoPlayer(
        name=team.name,
        team_id=ident(team),
        team_name=team.name,
        member_ids=sorted(members),
    )
