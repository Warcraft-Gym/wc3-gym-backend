"""The map veto of a series, step by step.

The board is derived: the event's pick_ban names the order and the side of
every step, the event pool names the maps, and a fixed rule takes its map off
the board because it is already game 1. Only the steps taken are stored. The
rules come from app.services.series_rules, so a bracket series with no
fixture opens the same board as a GNL one.
"""

from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col, select

from app.core.db import Session
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.core.map_order import DEFAULT_RULES, rules_of
from app.models.base import ident
from app.models.event_entrant import EventEntrant
from app.models.map import Map
from app.models.season import Season
from app.models.series import Series
from app.models.series_veto_step import (
    DBSeriesVetoStep,
    SeriesVetoPublic,
    SeriesVetoStepPublic,
    VetoPlayer,
)
from app.models.team import Team
from app.services.series_rules import (
    SeriesRules,
    acts_for_side,
    series_event,
    series_round,
    series_rules,
    stands_on_side,
)


class SeriesVetoService:
    def is_complete(self, series_id: int) -> bool:
        """Whether every step of the event's order is taken. An event with no
        order has nothing to take."""
        with Session() as session:
            series = session.get(Series, series_id)
            if not series:
                raise NotFoundError(f"Series not found by id: {series_id}")
            return len(_steps(session, series_id)) >= len(
                _order(series_event(session, series))
            )

    def board(
        self, series_id: int, user_id: int | None, player_id: int | None = None
    ) -> SeriesVetoPublic:
        """The board of one series. A null user is an admin, who reads any of them;
        player_id is the admin's own player row, so the board names the side they play."""
        with Session.begin() as session:
            series = _series(session, series_id, user_id)
            return _board(session, series, user_id if player_id is None else player_id)

    def take(
        self,
        series_id: int,
        user_id: int | None,
        action: str,
        map_id: int | None,
        entered_by: int | None = None,
    ) -> SeriesVetoPublic:
        """Take the step the order names next, record it for whichever side the
        order names when the veto happened elsewhere, or take back the last step
        the viewer entered. A null user is an admin: any side, any last step.
        The step records entered_by, the user when not given."""
        with Session.begin() as session:
            series = _series(session, series_id, user_id)
            steps = _steps(session, series_id)
            side = _letter(acts_for_side(session, series, user_id))
            if action == "undo":
                # A forced last step goes with the step that forced it: nobody took it
                undone = (
                    steps[-2:] if _forced_last(session, series, steps) else steps[-1:]
                )
                if not undone:
                    raise BadRequestError("The last step is not yours to take back")
                own = user_id == undone[0].entered_by or side == undone[0].side
                if user_id is not None and not own:
                    raise BadRequestError("The last step is not yours to take back")
                for step in undone:
                    session.delete(step)
            else:
                _take_step(
                    session,
                    series,
                    steps,
                    None if action == "record" or user_id is None else side,
                    map_id,
                    user_id if entered_by is None else entered_by,
                )
            session.flush()
            return _board(
                session, series, user_id if entered_by is None else entered_by
            )


def _series(session: OrmSession, series_id: int, user_id: int | None) -> Series:
    """The series, if the viewer plays it. A null user is an admin."""
    series = session.get(Series, series_id)
    if not series:
        raise NotFoundError(f"Series not found by id: {series_id}")
    if user_id is not None and acts_for_side(session, series, user_id) is None:
        raise ApiError(403, {"error": "not_authorized_for_this_series"})
    return series


def _steps(session: OrmSession, series_id: int) -> list[DBSeriesVetoStep]:
    return list(
        session.scalars(
            select(DBSeriesVetoStep)
            .where(col(DBSeriesVetoStep.series_id) == series_id)
            .order_by(col(DBSeriesVetoStep.step_no))
        )
    )


def _order(event: Season | None) -> list[str]:
    """The steps the event plays, for example Ban_A, Ban_B, Pick_A, Pick_B."""
    return [
        step for step in ((event.pick_ban if event else None) or "").split("|") if step
    ]


def _side(entry: str) -> str:
    return entry.rsplit("_", 1)[-1].upper()


STEPS = ("Ban_A", "Ban_B", "Pick_A", "Pick_B")


def veto_limits(season: Season) -> tuple[int, int]:
    """The picks the games take and the bans the pool then allows. A veto or
    loser game draws its map from the picks, a fixed game takes one map off
    the board, and every map left after the picks may be banned."""
    rules = (season.map_rules or DEFAULT_RULES).split(",")
    picks = sum(rule in ("veto", "loser") for rule in rules)
    pool = len(season.maps) - ("fixed" in rules)
    return picks, max(pool - picks, 0)


def check_order(season: Season) -> None:
    """Refuse an order the season cannot play through."""
    order = _order(season)
    for step in order:
        if step not in STEPS:
            raise BadRequestError(
                f"'{step}' is not a veto step. Valid steps are {', '.join(STEPS)}."
            )
    picks_max, bans_max = veto_limits(season)
    picks = sum(step.startswith("Pick") for step in order)
    bans = len(order) - picks
    if picks > picks_max:
        raise BadRequestError(
            f"The games take {picks_max} picks, the order has {picks}"
        )
    if bans > bans_max:
        raise BadRequestError(
            f"The pool allows {bans_max} bans after {picks_max} picks, the order has {bans}"
        )


def _fixed_map_id(
    session: OrmSession, series: Series, rules: SeriesRules
) -> int | None:
    """The map a fixed rule claims for game 1; it never enters the veto."""
    if "fixed" not in rules_of(rules.map_rules):
        return None
    row = series_round(session, series)
    return row.map_id if row else None


def _take_step(
    session: OrmSession,
    series: Series,
    steps: list[DBSeriesVetoStep],
    side: str | None,
    map_id: int | None,
    entered_by: int | None,
) -> None:
    """A null side records the step for whichever side the order names next."""
    rules = series_rules(session, series)
    order = _order(series_event(session, series))
    if len(steps) >= len(order):
        raise BadRequestError("The veto is complete")
    if side is not None and _side(order[len(steps)]) != side:
        raise BadRequestError("It is not your turn")
    if map_id not in set(rules.map_pool):
        raise BadRequestError(f"Map not part of the season, map id: {map_id}")
    if map_id in {step.map_id for step in steps}:
        raise BadRequestError(f"Map already used, map id: {map_id}")
    if map_id == _fixed_map_id(session, series, rules):
        raise BadRequestError(f"Map played as game 1, map id: {map_id}")
    session.add(
        DBSeriesVetoStep(
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
    fixed = _fixed_map_id(session, series, rules)
    left = [
        map_id for map_id in rules.map_pool if map_id not in taken and map_id != fixed
    ]
    if len(order) - len(steps) == 2 and len(left) == 1:
        session.add(
            DBSeriesVetoStep(
                series_id=ident(series),
                step_no=len(steps) + 2,
                side=_side(order[-1]),
                action=order[-1].split("_")[0].lower(),
                map_id=left[0],
            )
        )


def _forced_last(
    session: OrmSession, series: Series, steps: list[DBSeriesVetoStep]
) -> bool:
    """Whether the last step took itself: the order is complete and it used up
    the whole board, so one map was left for it."""
    rules = series_rules(session, series)
    order = _order(series_event(session, series))
    fixed = _fixed_map_id(session, series, rules)
    return len(order) >= 2 and len(steps) == len(order) == len(rules.map_pool) - (
        fixed is not None
    )


def _letter(side: int | None) -> str | None:
    """The side as the board spells it: A for the front side, B for the other."""
    return None if side is None else ("A" if side == 1 else "B")


def _veto_side(session: OrmSession, series: Series, side: int) -> VetoPlayer:
    """The name the board prints for one side: the player, or the team.

    `id` is the user of the side or nothing at all, so a client may compare it
    with its own user id; a team side names the team in its own two fields.
    """
    user = series.player1 if side == 1 else series.player2
    if user is not None:
        return VetoPlayer(id=ident(user), name=user.name)
    entrant_id = series.entrant1_id if side == 1 else series.entrant2_id
    entrant = session.get(EventEntrant, entrant_id) if entrant_id else None
    team = session.get(Team, entrant.team_id) if entrant and entrant.team_id else None
    if team is None:
        return VetoPlayer()
    return VetoPlayer(
        name=team.name,
        team_id=ident(team),
        team_name=team.name,
        team_icon_url=team.icon_url,
    )


def _board(
    session: OrmSession, series: Series, player_id: int | None
) -> SeriesVetoPublic:
    """The board as one player row sees it: an admin who plays gets their side and turn."""
    if stands_on_side(series, 1) is None or stands_on_side(series, 2) is None:
        raise BadRequestError("The series has no sides to veto with yet")
    rules = series_rules(session, series)
    order = _order(series_event(session, series))
    steps = _steps(session, ident(series))
    side = _letter(acts_for_side(session, series, player_id))
    complete = len(steps) >= len(order)
    return SeriesVetoPublic(
        steps=[
            SeriesVetoStepPublic.from_row(step, session.get(Map, step.map_id))
            for step in steps
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
