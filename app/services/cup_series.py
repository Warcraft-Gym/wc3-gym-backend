"""What a player or a runner writes on a cup series, and the reads behind it.

One rule decides every write: a player acts for the side they play (the
player a 1v1 side names, or a member of the team a team side fields), and a
runner of the cup (an admin, or one of its organizers) acts for either side.
A side reports and takes back its own played result; a walkover, a forfeit,
a forced reopen, lobby places and seats are a runner's.

Nothing here posts to Discord, uploads a replay or reads a GNL fixture.
"""

from typing import Any, Literal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core import map_order
from app.core.db import Session
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.core.outcome import scored, won_slot
from app.core.scoring import decided, recordable
from app.core.security import is_admin
from app.models.base import ident
from app.models.cup_series import (
    CupReportWrite,
    CupScoreWrite,
    CupSeries,
    CupSeriesGame,
    CupSeriesPublic,
    LobbyMapWrite,
)
from app.models.enums import Race
from app.models.event_entrant import EventEntrant
from app.models.series import ResultKindWrite
from app.models.series_game import SeriesGamePublic
from app.models.series_side import LobbySidesWrite, PlacesWrite
from app.models.series_veto_step import SeriesVetoPublic, SeriesVetoWrite
from app.models.user import User
from app.services import cup_engine, cup_reads, cup_veto, organizers, series_games

NOT_AUTHORIZED = {"error": "not_authorized_for_this_series"}


class CupReportPublic(CupSeriesPublic):
    """A reported result as the report dialog reads it back: the series, its
    games, and whether its veto was finished first."""

    veto_complete: bool = True
    games: list[SeriesGamePublic] = []


class Caller:
    """Who calls a cup series route: the player behind the account, and
    whether they run the cup the series is played in."""

    def __init__(
        self, session: OrmSession, claims: dict[str, Any] | None, row: CupSeries
    ) -> None:
        sub = (claims or {}).get("sub")
        self.user_id: int | None = (
            session.scalar(select(col(User.id)).where(col(User.discordId) == str(sub)))
            if sub and sub != "admin"
            else None
        )
        self.side: Literal[1, 2] | None = cup_reads.acts_for_side(
            session, row, self.user_id
        )
        self._claims = claims
        self._row = row
        self._session = session
        self._runs: bool | None = None

    @property
    def runs(self) -> bool:
        """Whether the caller runs the cup; read once, and only when asked. An
        admin runs every cup, so its check reads nothing."""
        if self._runs is None:
            self._runs = is_admin(self._claims) or organizers.runs_in(
                self._session,
                self._claims,
                ident(cup_reads.event_of(self._session, self._row)),
            )
        return self._runs

    def hold_side_or_runner(self) -> None:
        """Refuse a caller who plays neither side and does not run the cup."""
        if self.side is None and not self.runs:
            raise ApiError(403, NOT_AUTHORIZED)

    def hold_runner(self) -> None:
        """Refuse a caller who does not run the cup."""
        if not self.runs:
            raise ApiError(403, NOT_AUTHORIZED)

    def hold_seat_or_runner(self) -> None:
        """Refuse a caller who sits in no seat of the lobby and does not run the
        cup: every player of a lobby may enter its places, and in a team free
        for all every player of a team seated in it."""
        if self.user_id is not None and cup_engine.seated_in(
            self._session, self._row, self.user_id
        ):
            return
        self.hold_runner()


def get(series_id: int) -> CupSeriesPublic:
    """One cup series, as its box reads it."""
    with Session.begin() as session:
        return cup_engine.read_one(session, _series(session, series_id))


def games(series_id: int) -> list[SeriesGamePublic]:
    """Every game recorded for the series, in game order, each with its offer."""
    with Session() as session:
        row = _series(session, series_id)
        offers = _offers(session, row)
        return [
            SeriesGamePublic(
                game_no=game.game_no,
                winner_side=game.winner_side,
                map_id=game.map_id,
                offered_map_id=offers.get(game.game_no),
            )
            for game in _games(session, series_id)
        ]


def report(
    series_id: int, data: CupReportWrite, claims: dict[str, Any] | None
) -> CupReportPublic:
    """Report the result of a series for a side, with its games and the races
    played. A runner reports for either side."""
    with Session.begin() as session:
        row = _series(session, series_id)
        caller = Caller(session, claims, row)
        caller.hold_side_or_runner()
        wins = cup_engine.series_wins(session, row)
        reporting = data.player1_score is not None or data.player2_score is not None
        played: list[dict[str, Any]] = []
        if reporting:
            if data.player1_score is None or data.player2_score is None:
                raise BadRequestError("A result needs both map scores")
            if not decided(data.player1_score, data.player2_score, wins):
                raise BadRequestError(f"A series of this cup ends at {wins} map wins.")
            played = series_games.parse(data.games)
            if played:
                series_games.check(played, data.player1_score, data.player2_score)
        fields = data.model_fields_set
        races = {
            side: _race(getattr(data, side))
            for side in ("player1_off_race", "player2_off_race")
            if side in fields
        }
        _write(
            session,
            row,
            (data.player1_score, data.player2_score) if reporting else None,
            races,
            force=False,
        )
        if played:
            _record(session, series_id, played)
        complete = cup_veto.is_complete(session, row) if reporting else True
        answer = CupReportPublic.model_validate(
            cup_engine.read_one(session, row).model_dump()
        )
        answer.veto_complete = complete
        answer.games = [
            SeriesGamePublic(
                game_no=game.game_no, winner_side=game.winner_side, map_id=game.map_id
            )
            for game in _games(session, series_id)
        ]
        return answer


def score(
    series_id: int,
    data: CupScoreWrite,
    claims: dict[str, Any] | None,
    force: bool = False,
) -> CupSeriesPublic:
    """A runner writes or clears a result. Clearing reopens the series below;
    `force` allows it when a later series already carries a result."""
    with Session.begin() as session:
        row = _series(session, series_id)
        Caller(session, claims, row).hold_runner()
        fields = data.model_fields_set
        races = {
            side: getattr(data, side)
            for side in ("player1_off_race", "player2_off_race")
            if side in fields
        }
        result = (data.player1_score, data.player2_score)
        _write(session, row, result, races, force=force)
        return cup_engine.read_one(session, row)


def clear(
    series_id: int, claims: dict[str, Any] | None, force: bool = False
) -> CupSeriesPublic:
    """Take a result back: the scores, the races played and the games go. A
    side takes back its own played result; a walkover, a forfeit and `force`
    are a runner's."""
    with Session.begin() as session:
        row = _series(session, series_id)
        caller = Caller(session, claims, row)
        if cup_engine.lobby_seats(session, row):
            # a lobby's places are taken back by a runner, with the seats they sent on
            caller.hold_runner()
            cup_engine.clear_places(session, row)
            return cup_engine.read_one(session, row)
        if force or row.result_kind != "played":
            caller.hold_runner()
        else:
            caller.hold_side_or_runner()
        races: dict[str, Race | None] = {
            "player1_off_race": None,
            "player2_off_race": None,
        }
        _write(session, row, (None, None), races, force=force)
        return cup_engine.read_one(session, row)


def award(
    series_id: int, data: ResultKindWrite, claims: dict[str, Any] | None
) -> CupSeriesPublic:
    """A runner scores a series no game was played for: a walkover or a forfeit."""
    with Session.begin() as session:
        row = _series(session, series_id)
        Caller(session, claims, row).hold_runner()
        cup_engine.set_result_kind(session, row, data)
        return cup_engine.read_one(session, row)


def places(
    series_id: int, data: PlacesWrite, claims: dict[str, Any] | None
) -> CupSeriesPublic:
    """A player of a free for all lobby, or a runner, enters where every side
    finished; a lobby played already is corrected while the round after it is
    unplayed."""
    with Session.begin() as session:
        row = _series(session, series_id)
        Caller(session, claims, row).hold_seat_or_runner()
        cup_engine.set_places(session, row, data)
        return cup_engine.read_one(session, row)


def lobby_map(
    series_id: int, data: LobbyMapWrite, claims: dict[str, Any] | None
) -> CupSeriesPublic:
    """A runner plays a lobby on another map of the cup's pool."""
    with Session.begin() as session:
        row = _series(session, series_id)
        Caller(session, claims, row).hold_runner()
        cup_engine.set_lobby_map(session, row, data.map_id)
        return cup_engine.read_one(session, row)


def sides(
    series_id: int, data: LobbySidesWrite, claims: dict[str, Any] | None
) -> CupSeriesPublic:
    """A runner seats a free for all lobby again before it is played."""
    with Session.begin() as session:
        row = _series(session, series_id)
        Caller(session, claims, row).hold_runner()
        cup_engine.set_sides(session, row, data)
        return cup_engine.read_one(session, row)


def veto_board(series_id: int, claims: dict[str, Any] | None) -> SeriesVetoPublic:
    """The board of a series, for a player of either side or a runner."""
    with Session.begin() as session:
        row = _series(session, series_id)
        caller = Caller(session, claims, row)
        caller.hold_side_or_runner()
        return cup_veto.board(session, row, caller.user_id)


def veto_take(
    series_id: int, data: SeriesVetoWrite, claims: dict[str, Any] | None
) -> SeriesVetoPublic:
    """Take, record or take back a step of the veto."""
    with Session.begin() as session:
        row = _series(session, series_id)
        caller = Caller(session, claims, row)
        caller.hold_side_or_runner()
        runner = caller.side is None or (data.action != "step" and caller.runs)
        cup_veto.take(session, row, caller.user_id, data.action, data.map_id, runner)
        return cup_veto.board(session, row, caller.user_id)


def _series(session: OrmSession, series_id: int) -> CupSeries:
    row = session.get(CupSeries, series_id)
    if row is None:
        raise NotFoundError(f"Series not found by id: {series_id}")
    return row


def _race(named: str | None) -> Race | None:
    """A reported race in a player's words; an empty one clears it."""
    text = (named or "").strip()
    if not text:
        return None
    try:
        return Race.from_text(text)
    except ValueError as error:
        raise BadRequestError(str(error)) from error


def _write(
    session: OrmSession,
    row: CupSeries,
    result: tuple[int | None, int | None] | None,
    races: dict[str, Race | None],
    force: bool,
) -> None:
    """Write a result and the races played, and follow the result through the
    bracket. A cleared result takes its games and its kind with it, so the
    series reads as never reported. An off race that names the race the side
    entered on is no off race, so it is dropped."""
    was_scored = scored(row)
    was_slot = won_slot(row)
    if result is not None:
        first, second = result
        if (first is None) != (second is None):
            raise BadRequestError("A result needs both map scores")
        wins = cup_engine.series_wins(session, row)
        if (
            first is not None
            and second is not None
            and not recordable(first, second, wins)
        ):
            raise BadRequestError(
                f"A series of this cup ends at {wins} map wins, or 0-0 when it "
                "was never played"
            )
        row.player1_score, row.player2_score = first, second
    for side, race in races.items():
        setattr(row, side, race)
    _drop_kept_races(session, row)
    if was_scored and not scored(row):
        session.execute(
            delete(CupSeriesGame).where(col(CupSeriesGame.series_id) == ident(row))
        )
        row.result_kind = "played"
    session.flush()
    cup_engine.after_score(session, row, was_scored, was_slot, force)


def _drop_kept_races(session: OrmSession, row: CupSeries) -> None:
    """Clear an off race that is the race the side entered the cup on."""
    for entrant_id, field in (
        (row.entrant1_id, "player1_off_race"),
        (row.entrant2_id, "player2_off_race"),
    ):
        off_race = getattr(row, field)
        if off_race is None or entrant_id is None:
            continue
        entrant = session.get(EventEntrant, entrant_id)
        if entrant is not None and entrant.race == off_race:
            setattr(row, field, None)


def _record(session: OrmSession, series_id: int, played: list[dict[str, Any]]) -> None:
    """Write the games of a series, replacing whatever was recorded before."""
    session.execute(
        delete(CupSeriesGame).where(col(CupSeriesGame.series_id) == series_id)
    )
    for game in played:
        map_id = game.get("map_id")
        session.add(
            CupSeriesGame(
                series_id=series_id,
                game_no=int(game["game_no"]),
                winner_side=str(game["winner_side"]).upper(),
                map_id=int(map_id) if map_id else None,
            )
        )
    session.flush()


def _games(session: OrmSession, series_id: int) -> list[CupSeriesGame]:
    return list(
        session.scalars(
            select(CupSeriesGame)
            .where(col(CupSeriesGame.series_id) == series_id)
            .order_by(col(CupSeriesGame.game_no))
        )
    )


def _offers(session: OrmSession, row: CupSeries) -> dict[int, int | None]:
    """The map each game is played on when the cup vetoes by best-of: game 1
    on the map the veto left, every later game on the next pick of the side
    that lost. Another cup offers none."""
    event = cup_reads.event_of(session, row)
    if not event.veto_by_best_of:
        return {}
    rules = cup_reads.rules_of(session, row)
    steps = cup_veto.steps_of(session, ident(row))
    queue: dict[str, list[int]] = {}
    for step in steps:
        if step.action == "pick":
            queue.setdefault(step.side, []).append(step.map_id)
    order = map_order.cup_order(rules.best_of, len(rules.map_pool))
    decider = map_order.decider_of(
        rules.map_pool, [step.map_id for step in steps], len(steps) >= len(order)
    )
    winners = {
        game.game_no: game.winner_side
        for game in _games(session, ident(row))
        if game.winner_side is not None
    }
    return map_order.maps_by_game(
        rules.map_rules, None, {}, winners, queue=queue, decider=decider
    )
