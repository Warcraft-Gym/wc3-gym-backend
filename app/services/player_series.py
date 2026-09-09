import logging
from datetime import datetime
from typing import Any

from fastapi.responses import JSONResponse

from app.core.scoring import decided, wins_needed
from app.models.enums import Race
from app.models.series import SeriesUpdate
from app.services import discord_posts, replays, series_games
from app.services.series import SeriesService
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
) -> JSONResponse | dict[str, Any]:
    # Find the user by discord_id
    users = user_service.find_by_discord_id(discord_id)
    if not users:
        return JSONResponse({"error": "player_not_found"}, status_code=404)
    user = users[0]

    # Get the series and verify ownership
    series = series_service.get(series_id)
    if not series:
        return JSONResponse({"error": "series_not_found"}, status_code=404)

    # Check if user is player1 or player2 in this series
    if series.player1_id != user.id and series.player2_id != user.id:
        return JSONResponse(
            {"error": "not_authorized_for_this_series"}, status_code=403
        )

    # Track what's being updated for Discord notification
    original_datetime = series.date_time
    original_p1_score = series.player1_score
    original_p2_score = series.player2_score

    # One replay slot per game of the season's best-of, game1..gameN
    season = series.match.season if series.match else None
    wins = wins_needed(season.map_rules if season else None)
    action = data.get("action")

    # A result carries its veto: the record is what the map stats are made of
    reporting = action == "score_updated" or any(
        key in data for key in ("player1_score", "player2_score")
    )
    if reporting and not SeriesVetoService().is_complete(series_id):
        return JSONResponse(
            {
                "error": "The map veto is not complete. Enter it on the veto board first."
            },
            status_code=400,
        )

    # A result needs one replay per game played
    if reporting:
        try:
            p1 = int(data["player1_score"])
            p2 = int(data["player2_score"])
        except Exception:
            return JSONResponse(
                {"error": "Invalid or missing player scores for score update."},
                status_code=400,
            )
        if not decided(p1, p2, wins):
            return JSONResponse(
                {"error": f"A series of this season ends at {wins} map wins."},
                status_code=400,
            )

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
                return JSONResponse(
                    {
                        "error": "Invalid datetime format. Expected format: YYYY-MM-DD HH:MM:SS"
                    },
                    status_code=400,
                )
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
            return JSONResponse({"error": str(error)}, status_code=400)

    # The games of the report, checked against the score before anything is written
    games = series_games.parse(data.get("games")) if reporting else []
    if games:
        series_games.check(games, p1, p2)

    # The replays first: a game with no file in the bucket leaves the score unreported
    stored = (
        replays.confirm(series_id, range(1, p1 + p2 + 1), user.id) if reporting else []
    )

    # Only the fields this editor changes, so a concurrent edit stands
    updated_series = series_service.update(series_id, SeriesUpdate(**changes))

    # The bot's cards follow the write: the time on the announce card, the
    # score on the result card
    if original_datetime != updated_series.date_time:
        discord_posts.refresh_series(series_id)
    if (original_p1_score, original_p2_score) != (
        updated_series.player1_score,
        updated_series.player2_score,
    ):
        discord_posts.post_result(series_id)

    result = updated_series.to_dict()
    if reporting:
        result["replays"] = [replay.model_dump(mode="json") for replay in stored]
        if games:
            result["games"] = [
                game.model_dump(mode="json")
                for game in series_games.record(series_id, games)
            ]
    return result
