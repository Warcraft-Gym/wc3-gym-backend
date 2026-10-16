"""The routes of one cup series: its read, its report, its veto and the
runner's writes. A stage's draw and its tables stay under /events."""

from fastapi import APIRouter

from app.api.deps import RequireLogin
from app.models.cup_series import (
    CupReportWrite,
    CupScoreWrite,
    CupSeriesPublic,
    LobbyMapWrite,
    LobbyMoveWrite,
)
from app.models.series import ResultKindWrite
from app.models.series_game import SeriesGamePublic
from app.models.series_side import LobbySidesWrite, PlacesWrite
from app.models.series_veto_step import SeriesVetoPublic, SeriesVetoWrite
from app.services import cup_series
from app.services.cup_series import CupReportPublic

router = APIRouter(tags=["cup-series"])


@router.get("/cup-series/{series_id}")
def get_cup_series(series_id: int) -> CupSeriesPublic:
    """One cup series: its sides, its result, its rules and its races."""
    return cup_series.get(series_id)


@router.get("/cup-series/{series_id}/games")
def get_cup_series_games(series_id: int) -> list[SeriesGamePublic]:
    """Every game of a cup series, with the map the veto offers for each."""
    return cup_series.games(series_id)


@router.put("/cup-series/{series_id}/report")
def report_cup_series(
    series_id: int, data: CupReportWrite, claims: RequireLogin
) -> CupReportPublic:
    """Report a result, its games and the races played, for a side of the
    series; a runner of the cup reports for either side."""
    return cup_series.report(series_id, data, claims)


@router.put("/cup-series/{series_id}")
def score_cup_series(
    series_id: int, data: CupScoreWrite, claims: RequireLogin, force: bool = False
) -> CupSeriesPublic:
    """A runner of the cup writes or clears a result. Clearing reopens the
    bracket below; `force` allows it when a later series already has a result."""
    return cup_series.score(series_id, data, claims, force)


@router.delete("/cup-series/{series_id}/result")
def clear_cup_series_result(
    series_id: int, claims: RequireLogin, force: bool = False
) -> CupSeriesPublic:
    """Take a result back. A side takes back its own played result; a
    walkover, a forfeit and `force` are a runner's."""
    return cup_series.clear(series_id, claims, force)


@router.put("/cup-series/{series_id}/result-kind")
def award_cup_series(
    series_id: int, data: ResultKindWrite, claims: RequireLogin
) -> CupSeriesPublic:
    """A runner scores a series no game was played for: a walkover or a forfeit."""
    return cup_series.award(series_id, data, claims)


@router.put("/cup-series/{series_id}/places")
def place_cup_lobby(
    series_id: int, data: PlacesWrite, claims: RequireLogin
) -> CupSeriesPublic:
    """A player of a free for all lobby, or a runner, enters where every side
    finished: every seat once, places 1 to the seats that play, and no place
    for a Left seat (its entrant withdrew before the lobby was placed). A round whose every lobby has places seats the
    lobbies of the next round, and a correction seats it again while it is
    unplayed; once it has a result, 409."""
    return cup_series.places(series_id, data, claims)


@router.put("/cup-series/{series_id}/lobby-map")
def map_cup_lobby(
    series_id: int, data: LobbyMapWrite, claims: RequireLogin
) -> CupSeriesPublic:
    """A runner plays a lobby on another map of the cup's pool, until the lobby
    has its result."""
    return cup_series.lobby_map(series_id, data, claims)


@router.put("/cup-series/{series_id}/sides")
def seat_cup_lobby(
    series_id: int, data: LobbySidesWrite, claims: RequireLogin
) -> CupSeriesPublic:
    """A runner seats a free for all lobby again before it is played; an entrant
    seated in another lobby of the round moves with POST .../move instead."""
    return cup_series.sides(series_id, data, claims)


@router.post("/cup-series/{series_id}/move")
def move_cup_seat(
    series_id: int, data: LobbyMoveWrite, claims: RequireLogin
) -> list[CupSeriesPublic]:
    """A runner moves one entrant from this lobby to another of its round and
    division, both unplayed, in one write: the lobby left, then the lobby joined."""
    return cup_series.move(series_id, data, claims)


@router.get("/cup-series/{series_id}/veto")
def get_cup_series_veto(series_id: int, claims: RequireLogin) -> SeriesVetoPublic:
    """The map veto board, for a player of either side or a runner of the cup."""
    return cup_series.veto_board(series_id, claims)


@router.put("/cup-series/{series_id}/veto")
def set_cup_series_veto(
    series_id: int, data: SeriesVetoWrite, claims: RequireLogin
) -> SeriesVetoPublic:
    """Take the next step of your side, record a step taken elsewhere, or
    take back the last step. A runner records and takes back any step."""
    return cup_series.veto_take(series_id, data, claims)
