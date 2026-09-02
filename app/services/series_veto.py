"""The map veto of a series, step by step.

The board is derived: the season's pick_ban names the order and the side of
every step, the season pool names the maps, and a week rule takes its map off
the board because it is already game 1. Only the steps taken are stored.
"""

from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col, select

from app.core.db import Session
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.models.base import ident
from app.models.map import Map
from app.models.relationships import DBSeasonWeekMap
from app.models.season import Season
from app.models.series import Series
from app.models.series_veto_step import (
    DBSeriesVetoStep,
    SeriesVetoPublic,
    SeriesVetoStepPublic,
    VetoPlayer,
)


class SeriesVetoService:
    def is_complete(self, series_id: int) -> bool:
        """Whether every step of the season's order is taken. A season with no
        order has nothing to take."""
        with Session() as session:
            series = session.get(Series, series_id)
            if not series:
                raise NotFoundError(f"Series not found by id: {series_id}")
            return len(_steps(session, series_id)) >= len(_order(series.match.season))

    def board(self, series_id: int, user_id: int | None) -> SeriesVetoPublic:
        """The board of one series. A null user is an admin, who reads any of them."""
        with Session.begin() as session:
            return _board(session, _series(session, series_id, user_id), user_id)

    def take(
        self, series_id: int, user_id: int, action: str, map_id: int | None
    ) -> SeriesVetoPublic:
        """Take the step the order names next, record it for whichever side the
        order names when the veto happened elsewhere, or take back the last step
        the viewer entered."""
        with Session.begin() as session:
            series = _series(session, series_id, user_id)
            steps = _steps(session, series_id)
            side = "A" if user_id == series.player1_id else "B"
            if action == "undo":
                if not steps or user_id not in (
                    steps[-1].entered_by,
                    series.player1_id if steps[-1].side == "A" else series.player2_id,
                ):
                    raise BadRequestError("The last step is not yours to take back")
                session.delete(steps[-1])
            else:
                _take_step(
                    session,
                    series,
                    steps,
                    None if action == "record" else side,
                    map_id,
                    user_id,
                )
            session.flush()
            return _board(session, series, user_id)


def _series(session: OrmSession, series_id: int, user_id: int | None) -> Series:
    """The series, if the viewer plays it. A null user is an admin."""
    series = session.get(Series, series_id)
    if not series:
        raise NotFoundError(f"Series not found by id: {series_id}")
    if user_id is not None and user_id not in (series.player1_id, series.player2_id):
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


def _order(season: Season) -> list[str]:
    """The steps the season plays, for example Ban_A, Ban_B, Pick_A, Pick_B."""
    return [step for step in (season.pick_ban or "").split("|") if step]


def _side(entry: str) -> str:
    return entry.rsplit("_", 1)[-1].upper()


def _week_map_id(session: OrmSession, season: Season, playday: int) -> int | None:
    """The map a week rule claims for game 1; it never enters the veto."""
    if "week" not in (season.map_rules or "").split(","):
        return None
    row = session.get(DBSeasonWeekMap, (ident(season), playday))
    return row.map_id if row else None


def _take_step(
    session: OrmSession,
    series: Series,
    steps: list[DBSeriesVetoStep],
    side: str | None,
    map_id: int | None,
    user_id: int,
) -> None:
    """A null side records the step for whichever side the order names next."""
    season = series.match.season
    order = _order(season)
    if len(steps) >= len(order):
        raise BadRequestError("The veto is complete")
    if side is not None and _side(order[len(steps)]) != side:
        raise BadRequestError("It is not your turn")
    if map_id not in {link.map_id for link in season.maps}:
        raise BadRequestError(f"Map not part of the season, map id: {map_id}")
    if map_id in {step.map_id for step in steps}:
        raise BadRequestError(f"Map already used, map id: {map_id}")
    if map_id == _week_map_id(session, season, series.match.playday):
        raise BadRequestError(f"Map played as game 1, map id: {map_id}")
    session.add(
        DBSeriesVetoStep(
            series_id=ident(series),
            step_no=len(steps) + 1,
            side=_side(order[len(steps)]),
            # The order names the action; the client only names the map
            action=order[len(steps)].split("_")[0].lower(),
            map_id=map_id,
            entered_by=user_id,
        )
    )
    # The final step takes itself when one entry and one map remain: no choice is left
    taken = {step.map_id for step in steps} | {map_id}
    left = [
        link.map_id
        for link in season.maps
        if link.map_id not in taken
        and link.map_id != _week_map_id(session, season, series.match.playday)
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


def _board(
    session: OrmSession, series: Series, user_id: int | None
) -> SeriesVetoPublic:
    season = series.match.season
    order = _order(season)
    steps = _steps(session, ident(series))
    side = None
    if user_id == series.player1_id:
        side = "A"
    elif user_id == series.player2_id:
        side = "B"
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
        pool=[link.map_id for link in season.maps],
        week_map_id=_week_map_id(session, season, series.match.playday),
        map_rules=season.map_rules,
        player1=VetoPlayer(id=series.player1_id, name=series.player1.name),
        player2=VetoPlayer(id=series.player2_id, name=series.player2.name),
    )
