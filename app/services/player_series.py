import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.core.db import Session
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.core.scoring import decided, wins_needed, wins_of
from app.models.enums import Race
from app.models.series import Series, SeriesUpdate
from app.services import discord_posts, replays, series_games
from app.services.series import SeriesService
from app.services.series_rules import acts_for_side
from app.services.series_veto import SeriesVetoService
from app.services.users import UserService

logger = logging.getLogger(__name__)


def update_player_series(
    series_id: int,
    data: dict[str, Any],
    discord_id: str,
    discord_tag: str,
    user_service: UserService,
    series_service: SeriesService,
    admin: bool = False,
    runner: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """`runner` answers whether the caller organizes the series' event, who acts
    for either side as an admin does; it is asked only when nothing else lets
    the caller in, so a player's own report reads nothing more."""
    # Find the user by discord_id; an admin access token names no player
    users = user_service.find_by_discord_id(discord_id) if discord_id else []
    if not users and not admin:
        if runner is None or not runner():
            raise NotFoundError("player_not_found")
        admin = True
    user_id = users[0].id if users else None

    # Get the series and verify ownership
    series = series_service.get(series_id)
    if not series:
        raise NotFoundError("series_not_found")

    action = data.get("action")
    reporting = action == "score_updated" or any(
        key in data for key in ("player1_score", "player2_score")
    )
    # The races played belong to the result as well
    result_write = reporting or any(
        key in data for key in ("player1_off_race", "player2_off_race")
    )

    # The caller acts for a side, or is an admin, who acts for either. The
    # check writes nothing, so it reads in a session and opens no transaction.
    with Session() as session:
        row = session.get(Series, series_id)
        if row is None or not (admin or acts_for_side(session, row, user_id)):
            if row is None or runner is None or not runner():
                raise ApiError(403, {"error": "not_authorized_for_this_series"})
            admin = True
        # A player or a captain who changes a reported result is named in
        # Discord; an admin's correction is not
        before = (
            discord_posts.ResultFacts.read(session, row)
            if result_write and not admin and row.player1_score is not None
            else None
        )

    # One replay slot per game of the best-of the series plays, game1..gameN
    wins = wins_of(series.rules.best_of) if series.rules else wins_needed(None)
    # A result carries its veto, but a missing veto never holds a result back:
    # the answer says so and the caller warns
    veto_complete = SeriesVetoService().is_complete(series_id) if reporting else True

    if reporting:
        try:
            p1 = int(data["player1_score"])
            p2 = int(data["player2_score"])
        except Exception as invalid:
            raise BadRequestError(
                "Invalid or missing player scores for score update."
            ) from invalid
        if not decided(p1, p2, wins):
            raise BadRequestError(f"A series of this season ends at {wins} map wins.")

    # Update allowed fields (players can only update date_time and scores)
    changes: dict[str, Any] = {}
    if data.get("date_time"):
        if isinstance(data["date_time"], str):
            try:
                changes["date_time"] = datetime.fromisoformat(
                    data["date_time"].replace(" ", "T")
                )
            except ValueError as e:
                logger.error(
                    f"Invalid datetime format: {data['date_time']}, error: {e}"
                )
                raise BadRequestError(
                    "Invalid datetime format. Expected format: YYYY-MM-DD HH:MM:SS"
                ) from e
        else:
            changes["date_time"] = data["date_time"]
    if "player1_score" in data and data["player1_score"] is not None:
        changes["player1_score"] = int(data["player1_score"])
    if "player2_score" in data and data["player2_score"] is not None:
        changes["player2_score"] = int(data["player2_score"])

    # The race a side played, when it is not the one he signed the season up on.
    # An empty field clears it, so a player can take back a wrong report.
    for side in ("player1_off_race", "player2_off_race"):
        if side not in data:
            continue
        named = str(data[side] or "").strip()
        if not named:
            changes[side] = None
            continue
        try:
            changes[side] = Race.from_text(named)
        except ValueError as error:
            raise BadRequestError(str(error)) from error

    # The games of the report, checked against the score before anything is written
    games = series_games.parse(data.get("games")) if reporting else []
    if games:
        series_games.check(games, p1, p2)

    # A replay belongs with each game played, but a missing one never holds a result back:
    # the answer lists the games without one and the caller warns
    stored = (
        replays.confirm(series_id, range(1, p1 + p2 + 1), user_id, required=False)
        if reporting
        else []
    )

    # Only the fields this editor changes, so a concurrent edit stands
    updated_series = series_service.update(series_id, SeriesUpdate(**changes))
    discord_posts.follow_series(
        series_id, discord_posts.CardFacts.of(series), updated_series
    )

    result = updated_series.to_dict()
    if reporting:
        result["replays"] = [replay.model_dump(mode="json") for replay in stored]
        result["veto_complete"] = veto_complete
        held = {replay.game_no for replay in stored}
        result["replays_missing"] = [
            game for game in range(1, p1 + p2 + 1) if game not in held
        ]
        if games:
            result["games"] = [
                game.model_dump(mode="json")
                for game in series_games.record(series_id, games)
            ]
    # After the games are written, so the note compares the whole result
    if before is not None:
        discord_posts.post_result_change(series_id, before, user_id)
    return result
