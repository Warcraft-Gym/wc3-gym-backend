"""The games of a series: one row per game, in the order they were played.

A row names the side that won the game and the map it was played on. The two
scores on the series stay the total; these rows say how the total was reached,
which a 2-1 cannot. A game with no stored map is offered the map the season's
rules name, so a report confirms a map instead of hunting for it.
"""

import json
from typing import Any

from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col, delete, select

from app.core import map_order
from app.core.db import Session
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.relationships import round_row
from app.models.series import Series
from app.models.series_game import DBSeriesGame, SeriesGamePublic

SIDES = map_order.SIDES


def parse(value: object) -> list[dict[str, Any]]:
    """The games of a report, whether they arrive as JSON or as a form field."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as error:
            raise BadRequestError(f"Games are not valid JSON: {error}") from error
    if value is None:
        return []
    if not isinstance(value, list):
        raise BadRequestError("Games must be a list, one entry per game played")
    return value


def check(games: list[dict[str, Any]], player1_score: int, player2_score: int) -> None:
    """Refuse a set of games that does not add up to the score reported.

    One entry per game played, numbered from 1, each won by side A or side B,
    and each side winning as many games as its score claims.
    """
    played = player1_score + player2_score
    if len(games) != played:
        raise BadRequestError(
            f"A {player1_score}-{player2_score} result is {played} games, "
            f"{len(games)} given"
        )
    if sorted(int(game["game_no"]) for game in games) != list(range(1, played + 1)):
        raise BadRequestError(f"The games are numbered 1 to {played}, once each")
    sides = [str(game["winner_side"]).upper() for game in games]
    if any(side not in SIDES for side in sides):
        raise BadRequestError("Each game is won by side A or side B")
    won = {side: sides.count(side) for side in SIDES}
    if (won["A"], won["B"]) != (player1_score, player2_score):
        raise BadRequestError(
            f"The games give {won['A']}-{won['B']}, the result says "
            f"{player1_score}-{player2_score}"
        )


def record(series_id: int, games: list[dict[str, Any]]) -> list[SeriesGamePublic]:
    """Write the games of a series, replacing whatever was recorded before."""
    with Session.begin() as session:
        session.execute(
            delete(DBSeriesGame).where(col(DBSeriesGame.series_id) == series_id)
        )
        for game in games:
            map_id = game.get("map_id")
            session.add(
                DBSeriesGame(
                    series_id=series_id,
                    game_no=int(game["game_no"]),
                    winner_side=str(game["winner_side"]).upper(),
                    map_id=int(map_id) if map_id else None,
                )
            )
        session.flush()
    return for_series(series_id)


def _offers(session: OrmSession, series: Series) -> dict[int, int | None]:
    """The map the season's rules name for each game, given what is won so far."""
    season = series.match.season if series.match else None
    if season is None:
        return {}
    picks: dict[str, int | None] = {}
    for step in sorted(series.veto_steps, key=lambda step: step.step_no):
        if step.action == "pick":
            picks.setdefault(step.side, step.map_id)
    fixed_map_id = None
    if "fixed" in map_order.rules_of(season.map_rules) and series.match:
        row = round_row(session, series.match.season_id, series.match.playday)
        fixed_map_id = row.map_id if row else None
    winners = {
        game.game_no: game.winner_side
        for game in session.scalars(
            select(DBSeriesGame).where(col(DBSeriesGame.series_id) == series.id)
        )
    }
    return map_order.maps_by_game(season.map_rules, fixed_map_id, picks, winners)


def for_series(series_id: int) -> list[SeriesGamePublic]:
    """Every game recorded for this series, in game order, each with its offer."""
    with Session() as session:
        series = session.scalars(
            select(Series)
            .options(*Series._list_eager_options())
            .where(col(Series.id) == series_id)
        ).first()
        if not series:
            raise NotFoundError(f"Series not found by id: {series_id}")
        offers = _offers(session, series)
        rows = session.scalars(
            select(DBSeriesGame)
            .where(col(DBSeriesGame.series_id) == series_id)
            .order_by(col(DBSeriesGame.game_no))
        )
        return [
            SeriesGamePublic(
                game_no=row.game_no,
                winner_side=row.winner_side,
                map_id=row.map_id,
                offered_map_id=offers.get(row.game_no),
            )
            for row in rows
        ]


def offered(series_id: int) -> dict[int, int | None]:
    """The map to offer for each game, for a report that has none recorded."""
    with Session() as session:
        series = session.scalars(
            select(Series)
            .options(*Series._list_eager_options())
            .where(col(Series.id) == series_id)
        ).first()
        if not series:
            raise NotFoundError(f"Series not found by id: {series_id}")
        return _offers(session, series)
