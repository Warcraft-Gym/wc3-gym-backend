import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from app.api.deps import (
    AvailabilityServiceDep,
    Credentials,
    FantasyBetServiceDep,
    FantasyTeamServiceDep,
    SeasonServiceDep,
    SeriesServiceDep,
    SeriesVetoServiceDep,
    SettingsServiceDep,
    UserServiceDep,
    discord_token,
    require_login,
    require_member,
)
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.core.ordering import SortOrder
from app.core.query import QueryUtil
from app.models.fantasy_bet import (
    FantasyBetCreate,
    FantasyBetPublic,
    FantasyBetUpdate,
    PublicFantasyBetWrite,
)
from app.models.fantasy_team import (
    FantasyTeamCreate,
    FantasyTeamUpdate,
    PublicFantasyTeamWrite,
)
from app.models.login import PublicAccessRequest
from app.models.player_history import PlayerHistory
from app.models.series import SeriesSort
from app.models.series_veto_step import SeriesVetoPublic, SeriesVetoWrite
from app.models.types import utcnow
from app.models.user import (
    ProfileUpdate,
    PublicSignupWrite,
    UserCreate,
    UserListPublic,
    UserUpdate,
)
from app.models.user_season_availability import (
    PlayerAvailabilityWrite,
    UserSeasonAvailabilityPublic,
)
from app.services import discord, discord_roles, player_history, player_series
from app.services.seasons import SeasonService
from app.services.series import SeriesService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["public"])

# token -> {discord_id, discord_tag, season_id, expires_at, access_type}
_token_store: dict[str, dict[str, Any]] = {}


def _cleanup_expired() -> None:
    # use timezone-aware UTC now
    now = datetime.now(UTC)
    # a snapshot and a pop, because a parallel request can drop a token
    expired = [t for t, v in list(_token_store.items()) if v["expires_at"] <= now]
    for t in expired:
        _token_store.pop(t, None)


def _identity(
    request: Request,
    credentials: Credentials,
    token: str | None,
    access_type: str | None = None,
) -> dict[str, Any]:
    """Answer the Discord identity of a player request: the Clerk session, else the token."""
    # The token half goes when the bot posts static login links instead of signed ones.
    if credentials is not None:
        claims = require_member(request, credentials)
        if claims["sub"] == "admin":
            raise ApiError(401, {"error": "not_a_discord_member"})
        account = discord.identify(discord_token(claims["clerk_user_id"]).token)
        return {
            "discord_id": str(claims["sub"]),
            "discord_tag": account.get("global_name")
            or account.get("username")
            or str(claims["sub"]),
            "season_id": None,
            "access_type": access_type,
        }
    if not token:
        raise BadRequestError("missing token")
    _cleanup_expired()
    entry = _token_store.get(token)
    if not entry:
        raise NotFoundError("token_not_found_or_expired")
    if access_type and entry.get("access_type") != access_type:
        raise BadRequestError("invalid_token_type")
    return entry


def dashboard_player(
    request: Request,
    credentials: Credentials,
    user_service: UserServiceDep,
    token: str | None = None,
) -> tuple[dict[str, Any], UserListPublic]:
    """The identity behind a dashboard request, and the player row it names.

    As a dependency it reads the token off the query string; a route whose
    token arrives in the body calls it instead.
    """
    entry = _identity(request, credentials, token, "dashboard")
    users = user_service.find_by_discord_id(str(entry.get("discord_id")))
    if not users:
        raise NotFoundError("player_not_found")
    return entry, users[0]


DashboardPlayer = Annotated[
    tuple[dict[str, Any], UserListPublic], Depends(dashboard_player)
]


def _refuse_started(series_service: SeriesService, series_id: int | None) -> None:
    """A bet closes once its series has started, and reopens if the series moves later."""
    if series_id is None:
        return
    series = series_service.get(series_id)
    if series.date_time is not None and series.date_time <= utcnow():
        raise ApiError(
            403,
            {
                "error": "series_started",
                "message": "Bets close once the series has started",
            },
        )


def _refuse_unless_open(season_service: SeasonService, season_id: int) -> None:
    """A fantasy team is drafted before the season commences; the admin routes stay open."""
    phase = season_service.get(season_id).phase
    if phase == "commenced":
        raise ApiError(
            403,
            {"error": "season_commenced", "message": "The season has commenced"},
        )
    if phase == "complete":
        raise ApiError(
            403,
            {"error": "season_ended", "message": "The season has ended"},
        )


def _owned_bet(
    request: Request,
    credentials: Credentials,
    user_service: UserServiceDep,
    fantasy_bet_service: FantasyBetServiceDep,
    bet_id: int,
    token: str | None,
    verb: str,
) -> FantasyBetPublic:
    """The bet the identified player placed. Someone else's bet answers 403."""
    entry = _identity(request, credentials, token)
    users = user_service.find_by_discord_id(str(entry.get("discord_id")))
    if not users:
        raise NotFoundError("user_not_found")
    # get raises NotFoundError, which answers 404
    bet = fantasy_bet_service.get(bet_id)
    if bet.user_id != users[0].id:
        raise ApiError(
            403,
            {
                "error": "unauthorized",
                "message": f"You can only {verb} your own bets",
            },
        )
    return bet


@router.post("/public-access-helper", response_model=None)
def create_public_access_helper(
    request: Request,
    data: PublicAccessRequest | None = None,
    client_token: str | None = None,
    discord_id: str | None = None,
    discord_tag: str | None = None,
    season_id: str | None = None,
    access_type: str | None = None,
    ttl_minutes: str | None = None,
) -> dict[str, Any]:
    """Protected endpoint for the Discord bot to request a one-time public access URL. Requires BOT client token."""
    data = data or PublicAccessRequest()
    client_token = data.client_token or client_token
    expected = os.getenv("BOT_CLIENT_TOKEN") or ""
    if not expected or str(client_token) != str(expected):
        raise ApiError(401, {"error": "unauthorized"})

    discord_id = data.discord_id or discord_id
    discord_tag = data.discord_tag or discord_tag
    season_id = data.season_id or season_id
    access_type = data.access_type or access_type
    ttl = int(data.ttl_minutes or ttl_minutes or 30)

    if not discord_id or not discord_tag or not access_type:
        raise BadRequestError("missing parameters")

    if access_type not in ["signup", "dashboard", "fantasy"]:
        raise BadRequestError("invalid access_type")

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
def get_public_token(token: str) -> dict[str, Any]:
    """Return token metadata (used by public pages to validate token)."""
    _cleanup_expired()
    entry = _token_store.get(token)
    if not entry:
        raise NotFoundError("not_found")
    return {
        "discord_id": entry["discord_id"],
        "discord_tag": entry["discord_tag"],
        "season_id": entry["season_id"],
        "access_type": entry["access_type"],
    }


@router.delete("/public-token/{token}", response_model=None)
def delete_public_token(token: str) -> dict[str, Any]:
    """Remove a token after it has been used."""
    # a pop, because two parallel deletes must not both find the token
    if _token_store.pop(token, None) is not None:
        return {"status": "deleted"}
    raise NotFoundError("not_found")


@router.post("/signup", status_code=201, response_model=None)
def public_create_user(
    settings_service: SettingsServiceDep,
    user_service: UserServiceDep,
    season_service: SeasonServiceDep,
    request: Request,
    credentials: Credentials,
    data: PublicSignupWrite | None = None,
) -> dict[str, Any]:
    """Create user and optionally assign to season for the signed-in Discord member."""
    # A missing signups_enabled row leaves signups open
    try:
        signups_enabled = settings_service.get_by_key("signups_enabled").value
    except NotFoundError:
        signups_enabled = None
    if signups_enabled and signups_enabled.lower() == "false":
        raise ApiError(
            403,
            {
                "error": "signups_closed",
                "message": "Signups are currently closed",
            },
        )

    data = data or PublicSignupWrite()
    token = data.token
    entry = _identity(request, credentials, token, "signup")

    # Build user payload. Force discord fields from the identity to avoid spoofing.
    user_payload: dict[str, Any] = {
        "name": data.name,
        "battleTag": data.battleTag,
        "discordId": entry.get("discord_id"),
        "discordTag": entry.get("discord_tag"),
        "race": data.race,
        "mmr": data.mmr,
        "country": data.country,
        "timezone": data.timezone,
    }

    # Basic validation
    if not user_payload["name"] or not user_payload["battleTag"]:
        raise BadRequestError("missing user fields")

    # The route builds the model itself, so a rejected field is ours to answer
    try:
        user_create = UserCreate(**user_payload)
    except ValidationError as invalid:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in invalid.errors()
        )
        raise ApiError(422, {"error": problems}) from invalid

    # Validate BattleTag with W3Champions BEFORE creating/updating user
    if not user_service.validate_battle_tag(user_payload["battleTag"]):
        raise BadRequestError(
            f"BattleNet name '{user_payload['battleTag']}' is not valid"
            " - no W3Champions stats found"
        )

    # take the token here, because a pop lets only one parallel request continue
    if token and _token_store.pop(token, None) is None:
        raise NotFoundError("token_not_found_or_expired")

    # Check for existing user by discord id or tag
    existing_users = user_service.find_by_discord_id_or_tag(
        str(entry.get("discord_id")), str(entry.get("discord_tag"))
    )

    if existing_users and len(existing_users) > 0:
        # update first matched user
        existing = existing_users[0]
        # Validated as a whole profile, then written as the update it is
        user_create = UserCreate(**user_payload)
        user = user_service.update(existing.id, UserUpdate(**user_create.model_dump()))
    else:
        # create new user
        user = user_service.add(user_create)

    # Add to season if specified, on the race the form names
    # A commenced season takes the profile but no signup; an admin may add the player
    season_id = entry.get("season_id") or data.season_id or data.seasonId
    closed: str | None = None
    if season_id:
        season = season_service.get(int(season_id))
        if season.phase == "open":
            season_service.add_user_signup(int(season_id), [user.id], data.race)
        else:
            closed = (
                f"Signups for {season.name} are closed. Your profile is saved, but you"
                " are not in the season. An admin may add you; there is no guarantee."
            )

    # trigger W3C stats sync for the newly created/updated user (non-blocking)
    try:
        user_service.update_w3c_stats_by_id(user.id)
        logger.info(f"W3C sync triggered for user {user.id} after signup")
    except Exception as we:  # a refused sync must not fail the signup
        logger.warning(f"W3C sync failed after signup for user {user.id}: {we}")

    # The account is new to the guild's eyes; give it the roles it earns
    discord_roles.sync([user.id])

    if not user:
        raise ApiError(500, {"error": "user_creation_failed"})
    if closed:
        return user.to_dict() | {"signup": "closed", "message": closed}
    return user.to_dict()


@router.get("/player-series", response_model=None)
def get_player_series(
    user_service: UserServiceDep,
    series_service: SeriesServiceDep,
    availability_service: AvailabilityServiceDep,
    response: Response,
    request: Request,
    credentials: Credentials,
    token: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: SeriesSort | None = None,
    order: SortOrder = "asc",
) -> dict[str, Any]:
    """Get one page of a player's series for the dashboard view, at most 500.

    sort names the field the page is ordered by, and the series id breaks its ties.
    """
    # not a dependency: that would identify the player before limit is checked
    entry, user = dashboard_player(request, credentials, user_service, token)

    # Get series where user is player1 or player2
    # The token stores the season id as text
    season_id = int(entry["season_id"]) if entry.get("season_id") else None
    if season_id:
        query = QueryUtil.parse_query(
            f"player1_id == {user.id} or player2_id == {user.id}"
        )
        series = series_service.search_for_season(
            season_id,
            query,
            limit=limit,
            offset=offset,
            sort=sort,
            order=order,
        )
        total = series_service.count(query, season_id=season_id)
    else:
        # Search all series for this user
        query = QueryUtil.parse_query(
            f"player1_id == {user.id} or player2_id == {user.id}"
        )
        series = series_service.search(
            query, limit=limit, offset=offset, sort=sort, order=order
        )
        total = series_service.count(query)

    response.headers["X-Total-Count"] = str(total)

    # Convert to dict format
    series_data = [s.to_dict() for s in series]

    return {
        "player": user.to_dict(),
        "series": series_data,
        "season_id": entry.get("season_id"),
        "discord_id": entry.get("discord_id"),
        "discord_tag": entry.get("discord_tag"),
        "availability": availability_service.for_user(user.id, season_id)
        if season_id
        else [],
        "number_weeks": availability_service.season_weeks(season_id)
        if season_id
        else None,
    }


@router.put("/player-availability")
def set_player_availability(
    availability_service: AvailabilityServiceDep,
    settings_service: SettingsServiceDep,
    user_service: UserServiceDep,
    request: Request,
    credentials: Credentials,
    data: PlayerAvailabilityWrite,
) -> list[UserSeasonAvailabilityPublic]:
    """Write the identified player's answer for one week of a season.

    A null answer clears the week, which puts the player back to available.
    """
    entry, user = dashboard_player(request, credentials, user_service, data.token)

    season_id = (
        entry.get("season_id")
        or data.season_id
        or settings_service.get_settings_dict().get("current_gnl_season")
    )
    if not season_id:
        raise BadRequestError("missing season_id")

    return availability_service.set(
        user.id, int(season_id), data.playday, data.available, set_by_user_id=user.id
    )


@router.get("/player-history")
def get_player_history(player: DashboardPlayer) -> PlayerHistory:
    """Every GNL season this player took part in, and every opponent they met."""
    return player_history.history(player[1].id)


@router.put("/player-series/{series_id}", response_model=None)
async def update_player_series(
    series_id: int,
    request: Request,
    user_service: UserServiceDep,
    series_service: SeriesServiceDep,
    credentials: Credentials,
) -> JSONResponse | dict[str, Any]:
    """Update a series that belongs to the authenticated player."""
    # Handle both form data and JSON
    content_type = request.headers.get("content-type")
    data = {}
    files = {}
    if content_type and "multipart/form-data" in content_type:
        for key, value in (await request.form()).multi_items():
            if isinstance(value, UploadFile):
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
    entry = _identity(
        request, credentials, token if isinstance(token, str) else None, "dashboard"
    )

    # Only the parsing and the identity check above need the event loop
    return await run_in_threadpool(
        player_series.update_player_series,
        series_id,
        data,
        files,
        discord_id=str(entry.get("discord_id")),
        discord_tag=entry.get("discord_tag", "Unknown Player"),
        user_service=user_service,
        series_service=series_service,
    )


def _veto_viewer(
    request: Request,
    credentials: Credentials,
    token: str | None,
    user_service: UserServiceDep,
) -> int | None:
    """The player behind the request, or null for an admin, who only reads."""
    if credentials is not None:
        claims = require_login(request, credentials)
        if claims.get("role") == "admin" or claims.get("sub") == "admin":
            return None
    return dashboard_player(request, credentials, user_service, token)[1].id


@router.get("/player-series/{series_id}/veto")
def get_player_series_veto(
    series_id: int,
    user_service: UserServiceDep,
    veto_service: SeriesVetoServiceDep,
    request: Request,
    credentials: Credentials,
    token: str | None = None,
) -> SeriesVetoPublic:
    """The map veto board of a series, read by either player or by an admin."""
    viewer = _veto_viewer(request, credentials, token, user_service)
    return veto_service.board(series_id, viewer)


@router.put("/player-series/{series_id}/veto")
def set_player_series_veto(
    series_id: int,
    user_service: UserServiceDep,
    veto_service: SeriesVetoServiceDep,
    request: Request,
    credentials: Credentials,
    data: SeriesVetoWrite,
) -> SeriesVetoPublic:
    """Take the next step of the veto, or take back your own last one."""
    viewer = _veto_viewer(request, credentials, data.token, user_service)
    if viewer is None:
        raise ApiError(403, {"error": "not_authorized_for_this_series"})
    return veto_service.take(series_id, viewer, data.action, data.map_id)


@router.get("/user-info", response_model=None)
def get_user_info(
    user_service: UserServiceDep,
    request: Request,
    credentials: Credentials,
    token: str | None = None,
) -> dict[str, Any]:
    """Get user information (for fantasy team captains who may not be players)."""
    entry = _identity(request, credentials, token)

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
        "user": user.to_dict(),
        "discord_id": entry.get("discord_id"),
        "discord_tag": entry.get("discord_tag"),
        "season_id": entry.get("season_id"),
    }


@router.put("/user-info", response_model=None)
def update_user_info(
    user_service: UserServiceDep,
    request: Request,
    credentials: Credentials,
    data: ProfileUpdate,
) -> dict[str, Any]:
    """A member edits their own profile; open signups are not required for this."""
    entry = _identity(request, credentials, None, "profile")
    users = user_service.find_by_discord_id(str(entry.get("discord_id")))
    if not users:
        raise NotFoundError("No profile for this account")

    fields = data.model_dump(exclude_unset=True)
    if not fields:
        raise BadRequestError("No fields provided")
    tag = fields.get("battleTag")
    if tag and not user_service.validate_battle_tag(tag):
        raise BadRequestError(
            f"BattleNet name '{tag}' is not valid - no W3Champions stats found"
        )

    user = user_service.update(users[0].id, UserUpdate(**fields))
    if tag:
        try:  # a refused sync must not fail the edit
            user_service.update_w3c_stats_by_id(user.id)
        except Exception as we:
            logger.warning(f"W3C sync failed after profile edit for {user.id}: {we}")
    return {"user": user.to_dict()}


@router.post("/fantasy-team", status_code=201, response_model=None)
def create_fantasy_team(
    settings_service: SettingsServiceDep,
    user_service: UserServiceDep,
    fantasy_team_service: FantasyTeamServiceDep,
    season_service: SeasonServiceDep,
    request: Request,
    credentials: Credentials,
    data: PublicFantasyTeamWrite | None = None,
) -> dict[str, Any]:
    """Create or update fantasy team, creating user if needed."""
    # A missing fantasy_team_creation_enabled row leaves creation open
    try:
        fantasy_enabled = settings_service.get_by_key(
            "fantasy_team_creation_enabled"
        ).value
    except NotFoundError:
        fantasy_enabled = None
    if fantasy_enabled and fantasy_enabled.lower() == "false":
        raise ApiError(
            403,
            {
                "error": "fantasy_team_creation_closed",
                "message": "Fantasy team creation is currently closed",
            },
        )

    data = data or PublicFantasyTeamWrite()
    entry = _identity(request, credentials, data.token)

    # Validate required fields
    season_id = data.season_id
    drafted_team_id = data.drafted_team_id
    drafted_race = data.drafted_race
    player_ids = data.player_ids

    if not season_id or not drafted_team_id or not drafted_race:
        raise BadRequestError("missing required fields")
    _refuse_unless_open(season_service, season_id)

    # Find or create user
    users = user_service.find_by_discord_id(str(entry.get("discord_id")))

    if not users or len(users) == 0:
        # Create minimal user without battle tag validation (not a player)
        user_name = data.user_name or entry.get("discord_tag")
        battle_tag = data.battle_tag or entry.get("discord_tag")

        user_payload: dict[str, Any] = {
            "name": user_name,
            "battleTag": battle_tag,
            "discordId": entry.get("discord_id"),
            "discordTag": entry.get("discord_tag"),
            "race": "RANDOM",
        }

        user = user_service.add(UserCreate(**user_payload))
        logger.info(f"Created new user for fantasy team captain: {user.id}")
    else:
        user = users[0]

    # Check if team already exists
    team_query = QueryUtil.parse_query(
        f"captain_id == {user.id} and season_id == {season_id}"
    )
    existing_teams, _ = fantasy_team_service.search(team_query)

    team_data: dict[str, Any] = {
        # Use provided name or default to user name
        "name": data.name if "name" in data.model_fields_set else user.name,
        "season_id": season_id,
        "captain_id": user.id,
        "drafted_team_id": drafted_team_id,
        "drafted_race": drafted_race,
    }

    if existing_teams and len(existing_teams) > 0:
        # Update existing team
        team = fantasy_team_service.update(
            existing_teams[0].id, FantasyTeamUpdate(**team_data)
        )
        team_id = existing_teams[0].id
    else:
        # Create new team
        team = fantasy_team_service.add(FantasyTeamCreate(**team_data))
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
            fantasy_team_service.add_players(team_id, players_to_add)
        if players_to_remove:
            fantasy_team_service.remove_players(team_id, players_to_remove)

    # Return created/updated team
    final_team = fantasy_team_service.get(team_id)
    return final_team.to_dict()


@router.post("/fantasy-bet", status_code=201, response_model=None)
def create_fantasy_bet(
    user_service: UserServiceDep,
    fantasy_bet_service: FantasyBetServiceDep,
    series_service: SeriesServiceDep,
    request: Request,
    credentials: Credentials,
    data: PublicFantasyBetWrite | None = None,
) -> dict[str, Any] | None:
    """Create a fantasy bet for the identified player."""
    data = data or PublicFantasyBetWrite()
    entry = _identity(request, credentials, data.token)
    _refuse_started(series_service, data.series_id)

    # Get or create user based on discord info
    existing_users = user_service.find_by_discord_id(str(entry.get("discord_id")))
    user = existing_users[0] if existing_users else None

    if not user:
        raise ApiError(
            404,
            {
                "error": "user_not_found",
                "message": "You must register first before placing bets",
            },
        )

    # Create the bet
    bet_payload: dict[str, Any] = {
        "series_id": data.series_id,
        "season_id": data.season_id,
        "user_id": user.id,
        "winner_id": data.winner_id,
        "bet_points": data.bet_points,
    }

    try:
        bet = fantasy_bet_service.create_fantasy_bet(FantasyBetCreate(**bet_payload))
    except (BadRequestError, ValueError) as e:
        logger.error(f"Validation error creating bet: {e}")
        raise ApiError(400, {"error": "validation_error", "message": str(e)}) from e

    return bet.to_dict()


@router.put("/fantasy-bet/{bet_id}", response_model=None)
def update_fantasy_bet(
    bet_id: int,
    user_service: UserServiceDep,
    fantasy_bet_service: FantasyBetServiceDep,
    series_service: SeriesServiceDep,
    request: Request,
    credentials: Credentials,
    data: PublicFantasyBetWrite | None = None,
) -> dict[str, Any] | None:
    """Update a fantasy bet of the identified player."""
    data = data or PublicFantasyBetWrite()
    patch = data.model_dump(exclude_unset=True)
    existing_bet = _owned_bet(
        request,
        credentials,
        user_service,
        fantasy_bet_service,
        bet_id,
        data.token,
        "update",
    )
    _refuse_started(series_service, existing_bet.series_id)

    # Update the bet
    bet_payload = {
        "series_id": existing_bet.series_id,
        "season_id": existing_bet.season_id,
        "user_id": existing_bet.user_id,
        "winner_id": patch.get("winner_id", existing_bet.winner_id),
        "bet_points": patch.get("bet_points", existing_bet.bet_points),
    }

    try:
        bet = fantasy_bet_service.update_fantasy_bet(
            bet_id, FantasyBetUpdate(**bet_payload)
        )
    except (BadRequestError, ValueError) as e:
        logger.error(f"Validation error updating bet: {e}")
        raise ApiError(400, {"error": "validation_error", "message": str(e)}) from e

    return bet.to_dict()


@router.delete("/fantasy-bet/{bet_id}", status_code=204, response_model=None)
def delete_fantasy_bet(
    bet_id: int,
    user_service: UserServiceDep,
    fantasy_bet_service: FantasyBetServiceDep,
    series_service: SeriesServiceDep,
    request: Request,
    credentials: Credentials,
    token: str | None = None,
) -> None:
    """Delete a fantasy bet of the identified player."""
    bet = _owned_bet(
        request, credentials, user_service, fantasy_bet_service, bet_id, token, "delete"
    )
    _refuse_started(series_service, bet.series_id)
    fantasy_bet_service.delete(bet_id)
