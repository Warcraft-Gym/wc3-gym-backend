import json
import logging
import os
from datetime import datetime
from typing import Any

import requests
from fastapi.responses import JSONResponse

from app.core.security import secure_filename
from app.models.series import SeriesPublic, SeriesUpdate
from app.services.series import SeriesService
from app.services.users import UserService

logger = logging.getLogger(__name__)


def _notify_discord_series_update(
    series: SeriesPublic,
    player_name: str,
    action: str,
    uploaded_files: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """Send series update notification to Discord bot webhook with optional file attachments

    This function is designed to be non-blocking - if Discord notifications fail,
    the series update operation will still succeed.
    """
    try:
        bot_webhook_url = os.getenv("BOT_WEBHOOK_URL")
        bot_client_token = os.getenv("BOT_CLIENT_TOKEN")

        if not bot_webhook_url or not bot_client_token:
            logger.debug("Discord webhook not configured, skipping notification")
            return False

        # Prepare multipart form data for files
        if uploaded_files:
            # Create multipart form data manually using requests
            files_dict = {}

            series_json = json.dumps(
                series.to_dict() if hasattr(series, "to_dict") else series,
                sort_keys=True,
            )

            data_dict = {
                "series": series_json,
                "player_name": player_name,
                "action": action,
                "auth_token": bot_client_token,
            }

            # Add files to requests files dict
            for file_key, file_info in uploaded_files.items():
                files_dict[file_key] = (
                    file_info["filename"],
                    file_info["data"],
                    file_info["content_type"],
                )

            # Send webhook request with files
            response = requests.post(
                bot_webhook_url,
                data=data_dict,
                files=files_dict,
                timeout=30,  # Increased timeout for file uploads
            )
        else:
            # Send regular JSON payload
            payload = {
                "series": series.to_dict() if hasattr(series, "to_dict") else series,
                "player_name": player_name,
                "action": action,
                "auth_token": bot_client_token,
            }

            response = requests.post(
                bot_webhook_url,
                data=json.dumps(payload, sort_keys=True),
                timeout=5,
                headers={"Content-Type": "application/json"},
            )

        if response.status_code == 200:
            logger.info(f"Successfully notified Discord of series update: {action}")
            return True
        else:
            logger.warning(
                f"Discord webhook returned status {response.status_code}: {response.text}"
            )
            return False

    except requests.exceptions.Timeout:
        logger.warning(
            "Discord webhook request timed out - continuing without notification"
        )
        return False
    except requests.exceptions.ConnectionError:
        logger.warning("Discord webhook connection failed - bot may be offline")
        return False
    except Exception as e:
        logger.warning(
            f"Discord notification failed: {e} - series update will continue"
        )
        return False


def update_player_series(
    series_id: int,
    content_type: str | None,
    data: dict[str, Any],
    files: dict[str, dict[str, Any]],
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
    series = series_service.get_series(series_id)
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

    # Handle file uploads - prepare for Discord transmission
    uploaded_files = {}
    allowed_extensions = {"w3g"}

    # Debug logging
    logger.info(f"Request content type: {content_type}")
    logger.info(f"Form data keys: {list(data.keys())}")
    logger.info(f"Files keys: {list(files.keys())}")
    logger.info(
        f"Files details: {[(k, v['filename'] if v['filename'] else 'no filename') for k, v in files.items()]}"
    )

    def allowed_file(filename: str) -> bool:
        return (
            "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_extensions
        )

    for file_key in ["game1", "game2", "game3"]:
        if file_key in files and files[file_key]["filename"]:
            file = files[file_key]
            logger.info(f"Processing file {file_key}: {file['filename']}")
            if allowed_file(file["filename"]):
                uploaded_files[file_key] = {
                    "filename": secure_filename(file["filename"]),
                    "data": file["data"],
                    "content_type": file["content_type"] or "application/octet-stream",
                }
                logger.info(f"Prepared replay file for Discord: {file['filename']}")
            else:
                logger.warning(f"File {file_key} failed validation: {file['filename']}")
                return JSONResponse(
                    {
                        "error": f"Invalid file type for {file_key}. Only .w3g files are allowed."
                    },
                    status_code=400,
                )
        else:
            logger.info(f"No file found for {file_key}")

    logger.info(f"Final uploaded_files keys: {list(uploaded_files.keys())}")

    # Determine action: 'score_updated' or 'scheduled'. Frontend may send 'action'.
    action = data.get("action")
    logger.info(f"Action from request: {action}")

    # If the action explicitly indicates a result report, enforce file requirements.
    if action == "score_updated":
        logger.info("Processing as score update; enforcing replay upload requirements")
        logger.info(f"Game1 in uploaded_files: {'game1' in uploaded_files}")
        logger.info(f"Game2 in uploaded_files: {'game2' in uploaded_files}")

        if "game1" not in uploaded_files or "game2" not in uploaded_files:
            return JSONResponse(
                {
                    "error": "Game 1 and Game 2 replay files are required when reporting results."
                },
                status_code=400,
            )

        # Determine if game3 is required based on provided scores
        try:
            p1 = int(data.get("player1_score"))
            p2 = int(data.get("player2_score"))
        except Exception:
            # If scores are missing or invalid, reject
            return JSONResponse(
                {"error": "Invalid or missing player scores for score update."},
                status_code=400,
            )

        needs_game3 = (p1 == 2 and p2 == 1) or (p1 == 1 and p2 == 2)
        logger.info(f"Needs game3: {needs_game3}")
        if needs_game3 and "game3" not in uploaded_files:
            return JSONResponse(
                {"error": "Game 3 replay file is required for 2:1 or 1:2 results."},
                status_code=400,
            )
    else:
        # Backwards compatibility: if no explicit action provided, fall back to previous behavior
        scores_being_updated = "player1_score" in data or "player2_score" in data
        logger.info(f"Scores being updated (fallback): {scores_being_updated}")
        if scores_being_updated and (
            "game1" not in uploaded_files or "game2" not in uploaded_files
        ):
            return JSONResponse(
                {
                    "error": "Game 1 and Game 2 replay files are required when updating scores."
                },
                status_code=400,
            )

    # Update allowed fields (players can only update date_time and scores)
    changes: dict[str, Any] = {}
    if data.get("date_time"):
        if isinstance(data["date_time"], str):
            try:
                # The frontend sends ET, stored naive to match the DATETIME column
                changes["date_time"] = datetime.fromisoformat(
                    data["date_time"].replace(" ", "T")
                )

                logger.info(f"Storing ET datetime: {changes['date_time']}")
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

    # Only the fields this editor changes, so a concurrent edit stands
    updated_series = series_service.update_series(series_id, SeriesUpdate(**changes))

    # Determine notification action based on what was updated
    player_name = user.name if hasattr(user, "name") else discord_tag

    # Check if scores were updated
    scores_updated = (original_p1_score != updated_series.player1_score) or (
        original_p2_score != updated_series.player2_score
    )

    # Check if date/time was updated
    datetime_updated = original_datetime != updated_series.date_time

    # Prepare notification data - convert to dict for Discord serialization
    notification_data = (
        updated_series.to_dict()
        if hasattr(updated_series, "to_dict")
        else updated_series
    )

    # Attempt Discord notifications (non-blocking - app continues regardless of success/failure)
    discord_notified = False
    if scores_updated:
        discord_notified = _notify_discord_series_update(
            notification_data, player_name, "score_updated", uploaded_files
        )
    elif datetime_updated:
        discord_notified = _notify_discord_series_update(
            notification_data, player_name, "scheduled", uploaded_files
        )

    # Convert to dict only for JSON response
    result = (
        updated_series.to_dict()
        if hasattr(updated_series, "to_dict")
        else updated_series
    )
    if uploaded_files:
        result["uploaded_files"] = {k: v["filename"] for k, v in uploaded_files.items()}

    # Always include Discord notification status in response
    result["discord_notification_sent"] = discord_notified

    return result
