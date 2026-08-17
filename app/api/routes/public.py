import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Body, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.api.deps import (
    FantasyBetServiceDep,
    FantasyTeamServiceDep,
    SeasonServiceDep,
    SeriesServiceDep,
    SettingsServiceDep,
    UserServiceDep,
)
from app.core.exceptions import BadRequestError
from app.core.query import QueryUtil
from app.models.fantasy_bet import FantasyBetCreate, FantasyBetUpdate
from app.models.fantasy_team import FantasyTeamCreate, FantasyTeamUpdate
from app.models.user import UserCreate
from app.services import player_series

logger = logging.getLogger(__name__)

router = APIRouter(tags=["public"])

# token -> {discord_id, discord_tag, season_id, expires_at, access_type}
_token_store: dict[str, dict[str, Any]] = {}


def _cleanup_expired() -> None:
    # use timezone-aware UTC now
    now = datetime.now(UTC)
    expired = [t for t, v in _token_store.items() if v["expires_at"] <= now]
    for t in expired:
        del _token_store[t]


@router.post("/public-access-helper", response_model=None)
def create_public_access_helper(
    request: Request,
    data: Annotated[dict | None, Body()] = None,
    client_token: str | None = None,
    discord_id: str | None = None,
    discord_tag: str | None = None,
    season_id: str | None = None,
    access_type: str | None = None,
    ttl_minutes: str | None = None,
) -> JSONResponse | dict[str, Any]:
    """Protected endpoint for the Discord bot to request a one-time public access URL. Requires BOT client token."""
    data = data or {}
    client_token = data.get("client_token") or client_token
    expected = os.getenv("BOT_CLIENT_TOKEN") or ""
    if not expected or str(client_token) != str(expected):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    discord_id = data.get("discord_id") or discord_id
    discord_tag = data.get("discord_tag") or discord_tag
    season_id = data.get("season_id") or season_id
    access_type = data.get("access_type") or access_type
    ttl = int(data.get("ttl_minutes") or ttl_minutes or 30)

    if not discord_id or not discord_tag or not access_type:
        return JSONResponse({"error": "missing parameters"}, status_code=400)

    if access_type not in ["signup", "dashboard", "fantasy"]:
        return JSONResponse({"error": "invalid access_type"}, status_code=400)

    # cleanup store
    _cleanup_expired()

    token = secrets.token_urlsafe(16)
    expires_at = datetime.now(UTC) + timedelta(minutes=ttl)
    _token_store[token] = {
        "discord_id": str(discord_id),
        "discord_tag": str(discord_tag),
        "season_id": str(season_id) if season_id else None,
        "access_type": access_type,
        "expires_at": expires_at,
    }

    frontend = os.getenv("FRONTEND_URL") or str(request.base_url).rstrip("/")

    # Route based on access type
    if access_type == "signup":
        access_url = f"{frontend}#/signup?token={token}"
    elif access_type == "dashboard":
        access_url = f"{frontend}#/player-dashboard?token={token}"
    elif access_type == "fantasy":
        access_url = f"{frontend}#/fantasy-registration?token={token}"

    return {"access_url": access_url, "token": token}


@router.get("/public-token/{token}", response_model=None)
def get_public_token(token: str) -> JSONResponse | dict[str, Any]:
    """Return token metadata (used by public pages to validate token)."""
    _cleanup_expired()
    entry = _token_store.get(token)
    if not entry:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return {
        "discord_id": entry["discord_id"],
        "discord_tag": entry["discord_tag"],
        "season_id": entry["season_id"],
        "access_type": entry["access_type"],
    }


@router.delete("/public-token/{token}", response_model=None)
def delete_public_token(token: str) -> JSONResponse | dict[str, Any]:
    """Remove a token after it has been used."""
    if token in _token_store:
        del _token_store[token]
        return {"status": "deleted"}
    return JSONResponse({"error": "not_found"}, status_code=404)


@router.post("/signup", status_code=201, response_model=None)
def public_create_user(
    settings_service: SettingsServiceDep,
    user_service: UserServiceDep,
    season_service: SeasonServiceDep,
    data: Annotated[dict | None, Body()] = None,
) -> JSONResponse | dict[str, Any]:
    """Create user and optionally assign to season using a one-time token."""
    # Check if signups are enabled
    try:
        signup_enabled = settings_service.get_setting("signups_enabled")
        if signup_enabled and signup_enabled.get("value", "true").lower() == "false":
            return JSONResponse(
                {
                    "error": "signups_closed",
                    "message": "Signups are currently closed",
                },
                status_code=403,
            )
    except Exception as e:
        logger.warning(f"Could not check signups_enabled setting: {e}")
        # Continue if setting doesn't exist

    data = data or {}
    token = data.get("token")
    if not token:
        return JSONResponse({"error": "missing token"}, status_code=400)

    _cleanup_expired()
    entry = _token_store.get(token)
    if not entry:
        return JSONResponse({"error": "token_not_found_or_expired"}, status_code=404)

    if entry.get("access_type") != "signup":
        return JSONResponse({"error": "invalid_token_type"}, status_code=400)

    # Build user payload. Force discord fields from token to avoid spoofing.
    user_payload = {
        "name": data.get("name"),
        "battleTag": data.get("battleTag"),
        "discordId": entry.get("discord_id"),
        "discordTag": entry.get("discord_tag"),
        "race": data.get("race"),
        "mmr": data.get("mmr"),
        "country": data.get("country"),
    }

    # Basic validation
    if not user_payload["name"] or not user_payload["battleTag"]:
        return JSONResponse({"error": "missing user fields"}, status_code=400)

    # Validate BattleTag with W3Champions BEFORE creating/updating user
    if not user_service.validateBattleTag(user_payload["battleTag"]):
        return JSONResponse(
            {
                "error": f"BattleNet name '{user_payload['battleTag']}' is not valid - no W3Champions stats found"
            },
            status_code=400,
        )

    # Check for existing user by discord id or tag
    existing_users = user_service.find_by_discord_id_or_tag(
        str(entry.get("discord_id")), str(entry.get("discord_tag"))
    )

    if existing_users and len(existing_users) > 0:
        # update first matched user
        existing = existing_users[0]
        user_create = UserCreate(**user_payload)
        user = user_service.update_user(existing.id, user_create)
    else:
        # create new user
        user = user_service.create_user(UserCreate(**user_payload))

    # Add to season if specified
    season_id = entry.get("season_id") or data.get("season_id") or data.get("seasonId")
    if season_id:
        season_service.addUserSignup(int(season_id), [user.id])

    # trigger W3C stats sync for the newly created/updated user (non-blocking)
    try:
        user_service.updateW3CStats_ById(user.id)
        logger.info(f"W3C sync triggered for user {user.id} after signup")
    except Exception as we:
        logger.warning(f"W3C sync failed after signup for user {user.id}: {we}")

    # consume the token
    try:
        _token_store.pop(token, None)
    except Exception:
        logger.exception("Failed to delete token after signup")

    # return created user
    if user:
        try:
            out = user.to_dict()
        except Exception:
            out = user if isinstance(user, dict) else {}
        return out
    return JSONResponse({"error": "user_creation_failed"}, status_code=500)


@router.get("/player-series", response_model=None)
def get_player_series(
    user_service: UserServiceDep,
    series_service: SeriesServiceDep,
    token: str | None = None,
) -> JSONResponse | dict[str, Any]:
    """Get player's series for dashboard view using a one-time token."""
    if not token:
        return JSONResponse({"error": "missing token"}, status_code=400)

    _cleanup_expired()
    entry = _token_store.get(token)
    if not entry:
        return JSONResponse({"error": "token_not_found_or_expired"}, status_code=404)

    if entry.get("access_type") != "dashboard":
        return JSONResponse({"error": "invalid_token_type"}, status_code=400)

    # Find the user by discord_id
    users = user_service.find_by_discord_id(str(entry.get("discord_id")))
    if not users:
        return JSONResponse({"error": "player_not_found"}, status_code=404)
    user = users[0]

    # Get series where user is player1 or player2
    if entry.get("season_id"):
        # Use the series service searchForSeason method for season-specific queries
        query = QueryUtil.parseQuery(
            f"player1_id == {user.id} or player2_id == {user.id}"
        )
        series = series_service.searchForSeason(entry.get("season_id"), query)
    else:
        # Search all series for this user
        query = QueryUtil.parseQuery(
            f"player1_id == {user.id} or player2_id == {user.id}"
        )
        series = series_service.search(query)

    # Convert to dict format
    series_data = []
    for s in series:
        try:
            series_dict = s.to_dict() if hasattr(s, "to_dict") else s
            series_data.append(series_dict)
        except Exception:
            series_data.append(s if isinstance(s, dict) else {})

    return {
        "player": user.to_dict() if hasattr(user, "to_dict") else user,
        "series": series_data,
        "season_id": entry.get("season_id"),
        "discord_id": entry.get("discord_id"),
        "discord_tag": entry.get("discord_tag"),
    }


@router.put("/player-series/{series_id}", response_model=None)
async def update_player_series(
    series_id: int,
    request: Request,
    user_service: UserServiceDep,
    series_service: SeriesServiceDep,
) -> JSONResponse | dict[str, Any]:
    """Update a series that belongs to the authenticated player."""
    # Handle both form data and JSON
    content_type = request.headers.get("content-type")
    data = {}
    files = {}
    if content_type and "multipart/form-data" in content_type:
        for key, value in (await request.form()).multi_items():
            if hasattr(value, "filename"):
                if key not in files:
                    await value.seek(0)
                    files[key] = {
                        "filename": value.filename,
                        "data": await value.read(),
                        "content_type": value.content_type,
                    }
            else:
                data.setdefault(key, value)
    else:
        data = await request.json() or {}

    token = data.get("token")
    if not token:
        return JSONResponse({"error": "missing token"}, status_code=400)

    _cleanup_expired()
    entry = _token_store.get(token)
    if not entry:
        return JSONResponse({"error": "token_not_found_or_expired"}, status_code=404)

    if entry.get("access_type") != "dashboard":
        return JSONResponse({"error": "invalid_token_type"}, status_code=400)

    # Only the parsing and the token check above need the event loop
    return await run_in_threadpool(
        player_series.update_player_series,
        series_id,
        content_type,
        data,
        files,
        discord_id=str(entry.get("discord_id")),
        discord_tag=entry.get("discord_tag", "Unknown Player"),
        user_service=user_service,
        series_service=series_service,
    )


@router.get("/user-info", response_model=None)
def get_user_info(
    user_service: UserServiceDep, token: str | None = None
) -> JSONResponse | dict[str, Any]:
    """Get user information by token (for fantasy team captains who may not be players)."""
    if not token:
        return JSONResponse({"error": "missing token"}, status_code=400)

    _cleanup_expired()
    entry = _token_store.get(token)
    if not entry:
        return JSONResponse({"error": "token_not_found_or_expired"}, status_code=404)

    # Find the user by discord_id
    users = user_service.find_by_discord_id(str(entry.get("discord_id")))

    if not users or len(users) == 0:
        # User doesn't exist yet
        return {
            "user": None,
            "discord_id": entry.get("discord_id"),
            "discord_tag": entry.get("discord_tag"),
            "season_id": entry.get("season_id"),
        }

    user = users[0]
    return {
        "user": user.to_dict() if hasattr(user, "to_dict") else user,
        "discord_id": entry.get("discord_id"),
        "discord_tag": entry.get("discord_tag"),
        "season_id": entry.get("season_id"),
    }


@router.post("/fantasy-team", status_code=201, response_model=None)
def create_fantasy_team(
    settings_service: SettingsServiceDep,
    user_service: UserServiceDep,
    fantasy_team_service: FantasyTeamServiceDep,
    data: Annotated[dict | None, Body()] = None,
) -> JSONResponse | dict[str, Any]:
    """Create or update fantasy team, creating user if needed."""
    # Check if fantasy team creation is enabled
    try:
        fantasy_enabled = settings_service.get_setting("fantasy_team_creation_enabled")
        if fantasy_enabled and fantasy_enabled.get("value", "true").lower() == "false":
            return JSONResponse(
                {
                    "error": "fantasy_team_creation_closed",
                    "message": "Fantasy team creation is currently closed",
                },
                status_code=403,
            )
    except Exception as e:
        logger.warning(f"Could not check fantasy_team_creation_enabled setting: {e}")
        # Continue if setting doesn't exist

    data = data or {}
    token = data.get("token")
    if not token:
        return JSONResponse({"error": "missing token"}, status_code=400)

    _cleanup_expired()
    entry = _token_store.get(token)
    if not entry:
        return JSONResponse({"error": "token_not_found_or_expired"}, status_code=404)

    # Validate required fields
    season_id = data.get("season_id")
    drafted_team_id = data.get("drafted_team_id")
    drafted_race = data.get("drafted_race")
    player_ids = data.get("player_ids", [])

    if not season_id or not drafted_team_id or not drafted_race:
        return JSONResponse({"error": "missing required fields"}, status_code=400)

    # Find or create user
    users = user_service.find_by_discord_id(str(entry.get("discord_id")))

    if not users or len(users) == 0:
        # Create minimal user without battle tag validation (not a player)
        user_name = data.get("user_name") or entry.get("discord_tag")
        battle_tag = data.get("battle_tag") or entry.get("discord_tag")

        user_payload = {
            "name": user_name,
            "battleTag": battle_tag,
            "discordId": entry.get("discord_id"),
            "discordTag": entry.get("discord_tag"),
            "race": "RANDOM",
        }

        user = user_service.create_user(UserCreate(**user_payload))
        logger.info(f"Created new user for fantasy team captain: {user.id}")
    else:
        user = users[0]

    # Check if team already exists
    team_query = QueryUtil.parseQuery(
        f"captain_id == {user.id} and season_id == {season_id}"
    )
    existing_teams = fantasy_team_service.search_fantasy_teams(team_query)

    team_data = {
        "name": data.get(
            "name", user.name
        ),  # Use provided name or default to user name
        "season_id": season_id,
        "captain_id": user.id,
        "drafted_team_id": drafted_team_id,
        "drafted_race": drafted_race,
    }

    if existing_teams and len(existing_teams) > 0:
        # Update existing team
        team = fantasy_team_service.update_fantasy_team(
            existing_teams[0].id, FantasyTeamUpdate(**team_data)
        )
        team_id = existing_teams[0].id
    else:
        # Create new team
        team = fantasy_team_service.create_fantasy_team(FantasyTeamCreate(**team_data))
        team_id = team.id

    # Update players if provided
    if player_ids and len(player_ids) > 0:
        # Get existing players
        existing_player_ids = [
            p.id
            for p in (
                existing_teams[0].drafted_players
                if existing_teams and existing_teams[0].drafted_players
                else []
            )
        ]

        # Find players to add and remove
        players_to_add = [pid for pid in player_ids if pid not in existing_player_ids]
        players_to_remove = [
            pid for pid in existing_player_ids if pid not in player_ids
        ]

        if players_to_add:
            fantasy_team_service.addFantasyPlayers(team_id, players_to_add)
        if players_to_remove:
            fantasy_team_service.removeFantasyPlayers(team_id, players_to_remove)

    # Return created/updated team
    final_team = fantasy_team_service.get_fantasy_team(team_id)
    return final_team.to_dict() if hasattr(final_team, "to_dict") else final_team


@router.post("/fantasy-bet", status_code=201, response_model=None)
def create_fantasy_bet(
    user_service: UserServiceDep,
    fantasy_bet_service: FantasyBetServiceDep,
    data: Annotated[dict | None, Body()] = None,
) -> JSONResponse | dict[str, Any] | None:
    """Create a fantasy bet using a token."""
    try:
        data = data or {}
        token = data.get("token")

        if not token:
            return JSONResponse({"error": "missing token"}, status_code=400)

        _cleanup_expired()
        entry = _token_store.get(token)
        if not entry:
            return JSONResponse(
                {"error": "token_not_found_or_expired"}, status_code=404
            )

        # Get or create user based on discord info

        user = None
        try:
            existing_users = user_service.find_by_discord_id(
                str(entry.get("discord_id"))
            )
            if existing_users and len(existing_users) > 0:
                user = existing_users[0]
        except Exception as e:
            logger.error(f"Error searching for user: {e}")
            return JSONResponse({"error": "user_lookup_failed"}, status_code=500)

        if not user:
            return JSONResponse(
                {
                    "error": "user_not_found",
                    "message": "You must register first before placing bets",
                },
                status_code=404,
            )

        # Create the bet
        bet_payload = {
            "series_id": data.get("series_id"),
            "season_id": data.get("season_id"),
            "user_id": user.id,
            "winner_id": data.get("winner_id"),
            "bet_points": data.get("bet_points"),
        }

        bet = fantasy_bet_service.create_fantasy_bet(FantasyBetCreate(**bet_payload))

        return bet.to_dict() if hasattr(bet, "to_dict") else bet

    except (BadRequestError, ValueError) as e:
        logger.error(f"Validation error creating bet: {e}")
        return JSONResponse(
            {"error": "validation_error", "message": str(e)}, status_code=400
        )


@router.put("/fantasy-bet/{bet_id}", response_model=None)
def update_fantasy_bet(
    bet_id: int,
    user_service: UserServiceDep,
    fantasy_bet_service: FantasyBetServiceDep,
    data: Annotated[dict | None, Body()] = None,
) -> JSONResponse | dict[str, Any] | None:
    """Update a fantasy bet using a token."""
    try:
        data = data or {}
        token = data.get("token")

        if not token:
            return JSONResponse({"error": "missing token"}, status_code=400)

        _cleanup_expired()
        entry = _token_store.get(token)
        if not entry:
            return JSONResponse(
                {"error": "token_not_found_or_expired"}, status_code=404
            )

        # Get user based on discord info

        user = None
        try:
            existing_users = user_service.find_by_discord_id(
                str(entry.get("discord_id"))
            )
            if existing_users and len(existing_users) > 0:
                user = existing_users[0]
        except Exception as e:
            logger.error(f"Error searching for user: {e}")
            return JSONResponse({"error": "user_lookup_failed"}, status_code=500)

        if not user:
            return JSONResponse({"error": "user_not_found"}, status_code=404)

        # Get the existing bet to verify ownership
        existing_bet = fantasy_bet_service.get_fantasy_bet(bet_id)
        if not existing_bet:
            return JSONResponse({"error": "bet_not_found"}, status_code=404)

        # Verify that the bet belongs to this user
        if existing_bet.user_id != user.id:
            return JSONResponse(
                {
                    "error": "unauthorized",
                    "message": "You can only update your own bets",
                },
                status_code=403,
            )

        # Update the bet
        bet_payload = {
            "series_id": existing_bet.series_id,
            "season_id": existing_bet.season_id,
            "user_id": user.id,
            "winner_id": data.get("winner_id", existing_bet.winner_id),
            "bet_points": data.get("bet_points", existing_bet.bet_points),
        }

        bet = fantasy_bet_service.update_fantasy_bet(
            bet_id, FantasyBetUpdate(**bet_payload)
        )

        return bet.to_dict() if hasattr(bet, "to_dict") else bet

    except (BadRequestError, ValueError) as e:
        logger.error(f"Validation error updating bet: {e}")
        return JSONResponse(
            {"error": "validation_error", "message": str(e)}, status_code=400
        )


@router.delete("/fantasy-bet/{bet_id}", status_code=204, response_model=None)
def delete_fantasy_bet(
    bet_id: int,
    user_service: UserServiceDep,
    fantasy_bet_service: FantasyBetServiceDep,
    token: str | None = None,
) -> JSONResponse | None:
    """Delete a fantasy bet using a token."""
    if not token:
        return JSONResponse({"error": "missing token"}, status_code=400)

    _cleanup_expired()
    entry = _token_store.get(token)
    if not entry:
        return JSONResponse({"error": "token_not_found_or_expired"}, status_code=404)

    # Get user based on discord info

    user = None
    try:
        existing_users = user_service.find_by_discord_id(str(entry.get("discord_id")))
        if existing_users and len(existing_users) > 0:
            user = existing_users[0]
    except Exception as e:
        logger.error(f"Error searching for user: {e}")
        return JSONResponse({"error": "user_lookup_failed"}, status_code=500)

    if not user:
        return JSONResponse({"error": "user_not_found"}, status_code=404)

    # Get the existing bet to verify ownership
    existing_bet = fantasy_bet_service.get_fantasy_bet(bet_id)
    if not existing_bet:
        return JSONResponse({"error": "bet_not_found"}, status_code=404)

    # Verify that the bet belongs to this user
    if existing_bet.user_id != user.id:
        return JSONResponse(
            {
                "error": "unauthorized",
                "message": "You can only delete your own bets",
            },
            status_code=403,
        )

    # Delete the bet
    fantasy_bet_service.delete_fantasy_bet(bet_id)
