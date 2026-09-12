import logging
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from sqlmodel import SQLModel
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
    SoftBlockServiceDep,
    UserServiceDep,
    claim_seats,
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
from app.models.player_history import PlayerHistory
from app.models.series import PlayerSeriesWrite, SeriesPublic, SeriesSort
from app.models.series_game import SeriesGamePublic
from app.models.series_replay import SeriesReplayPublic
from app.models.series_veto_step import SeriesVetoPublic, SeriesVetoWrite
from app.models.types import utcnow
from app.models.user import (
    ProfileUpdate,
    PublicSignupWrite,
    UserCreate,
    UserListPublic,
    UserUpdate,
)
from app.models.user_block import (
    FreeTimePublic,
    SoftBlocksPublic,
    UserBlockCreate,
    UserBlockPublic,
    UserBlockUpdate,
    UserBusyCreate,
    UserBusyPublic,
    UserBusyUpdate,
)
from app.models.user_season_availability import (
    PlayerAvailabilityWrite,
    UserSeasonAvailabilityPublic,
)
from app.services import (
    discord,
    discord_posts,
    discord_roles,
    player_history,
    player_series,
    replays,
    series_games,
)
from app.services.series import SeriesService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["public"])


def _validated[T: SQLModel](model: type[T], fields: dict[str, Any]) -> T:
    """A body the route assembles itself, refused the way FastAPI refuses one."""
    try:
        return model(**fields)
    except ValidationError as invalid:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in invalid.errors()
        )
        raise ApiError(422, {"error": problems}) from invalid


def _identity(request: Request, credentials: Credentials) -> dict[str, Any]:
    """The Discord identity behind a player request: the member's Clerk session."""
    claims = require_member(request, credentials)
    if claims["sub"] == "admin":
        raise ApiError(401, {"error": "not_a_discord_member"})
    account = discord.identify(discord_token(claims["clerk_user_id"]).token)
    return {
        "discord_id": str(claims["sub"]),
        "discord_tag": account.get("global_name")
        or account.get("username")
        or str(claims["sub"]),
        "season_id": discord_roles.current_season(),
    }


def dashboard_player(
    request: Request,
    credentials: Credentials,
    user_service: UserServiceDep,
) -> tuple[dict[str, Any], UserListPublic]:
    """The identity behind a dashboard request, and the player row it names."""
    entry = _identity(request, credentials)
    users = user_service.find_by_discord_id(str(entry.get("discord_id")))
    if not users:
        raise NotFoundError("player_not_found")
    return entry, users[0]


DashboardPlayer = Annotated[
    tuple[dict[str, Any], UserListPublic], Depends(dashboard_player)
]


def _refuse_started(
    series_service: SeriesService, series_id: int | None
) -> SeriesPublic | None:
    """The series the bet names, once it is still open: a bet closes when the
    series is scored or past its time, and reopens if the series moves later."""
    if series_id is None:
        return None
    series = series_service.get(series_id)
    # The same rule the season phase reads (app/models/season.py started)
    scored = series.player1_score is not None and series.player2_score is not None
    if scored or (series.date_time is not None and series.date_time <= utcnow()):
        raise ApiError(
            403,
            {
                "error": "series_started",
                "message": "Bets close once the series has started",
            },
        )
    return series


def _owned_bet(
    request: Request,
    credentials: Credentials,
    user_service: UserServiceDep,
    fantasy_bet_service: FantasyBetServiceDep,
    bet_id: int,
    verb: str,
) -> FantasyBetPublic:
    """The bet the identified player placed. Someone else's bet answers 403."""
    entry = _identity(request, credentials)
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


@router.post("/signup", status_code=201, response_model=None)
def public_create_user(
    user_service: UserServiceDep,
    season_service: SeasonServiceDep,
    request: Request,
    credentials: Credentials,
    data: PublicSignupWrite | None = None,
) -> dict[str, Any]:
    """Create user and optionally assign to season for the signed-in Discord member."""
    data = data or PublicSignupWrite()
    entry = _identity(request, credentials)

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
    user_create = _validated(UserCreate, user_payload)

    # Validate BattleTag with W3Champions BEFORE creating/updating user
    if not user_service.validate_battle_tag(user_payload["battleTag"]):
        raise BadRequestError(
            f"BattleNet name '{user_payload['battleTag']}' is not valid"
            " - no W3Champions stats found"
        )

    # Check for existing user by discord id or tag
    existing_users = user_service.find_by_discord_id_or_tag(
        str(entry.get("discord_id")), str(entry.get("discord_tag"))
    )

    if existing_users and len(existing_users) > 0:
        # update first matched user
        # Only the fields the form sent: an omitted one, such as mmr, keeps its value
        user = user_service.update(
            existing_users[0].id,
            UserUpdate(
                **data.model_dump(
                    exclude_unset=True, exclude={"season_id", "seasonId"}
                ),
                discordId=entry.get("discord_id"),
                discordTag=entry.get("discord_tag"),
            ),
        )
    else:
        # create new user
        user = user_service.add(user_create)

    # Add to season if specified, on the race the form names
    # A closed or non-open season takes the profile only; an admin may add them
    season_id = data.season_id or data.seasonId or entry.get("season_id")
    closed: str | None = None
    if season_id:
        season = season_service.get(int(season_id))
        if season.phase == "open" and season.signups_open:
            season_service.add_user_signup(
                int(season_id), [user.id], user_create.race.value
            )
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
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: SeriesSort | None = None,
    order: SortOrder = "asc",
    season_id: int | None = None,
) -> dict[str, Any]:
    """Get one page of a player's series for the dashboard view, at most 500.

    sort names the field the page is ordered by, and the series id breaks its ties.
    season_id picks the season; without it the identity's own season answers.
    """
    # not a dependency: that would identify the player before limit is checked
    entry, user = dashboard_player(request, credentials, user_service)

    # Get series where user is player1 or player2
    season_id = season_id or entry["season_id"]
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
        "season_id": season_id,
        "discord_id": entry.get("discord_id"),
        "discord_tag": entry.get("discord_tag"),
        "availability": availability_service.for_user(user.id, season_id)
        if season_id
        else [],
        "round_count": availability_service.season_weeks(season_id)
        if season_id
        else None,
        "rounds": availability_service.season_rounds(season_id) if season_id else [],
    }


@router.put("/player-availability")
def set_player_availability(
    availability_service: AvailabilityServiceDep,
    user_service: UserServiceDep,
    request: Request,
    credentials: Credentials,
    data: PlayerAvailabilityWrite,
) -> list[UserSeasonAvailabilityPublic]:
    """Write the identified player's answer for one week of a season.

    A null answer clears the week, which puts the player back to available.
    """
    entry, user = dashboard_player(request, credentials, user_service)

    season_id = data.season_id or entry["season_id"]
    if not season_id:
        raise BadRequestError("missing season_id")

    return availability_service.set(
        user.id, int(season_id), data.playday, data.available, set_by_user_id=user.id
    )


@router.get("/player-blocks")
def get_player_blocks(
    player: DashboardPlayer, service: SoftBlockServiceDep
) -> SoftBlocksPublic:
    """The signed-in player's own repeating blocks and busy days."""
    return service.for_user(player[1].id)


@router.post("/player-blocks/repeating", status_code=201)
def add_player_block(
    data: UserBlockCreate, player: DashboardPlayer, service: SoftBlockServiceDep
) -> UserBlockPublic:
    """Add a repeating block: local hours on some weekdays, in the player's zone."""
    return service.add_block(player[1].id, data)


@router.put("/player-blocks/repeating/{block_id}")
def update_player_block(
    block_id: int,
    data: UserBlockUpdate,
    player: DashboardPlayer,
    service: SoftBlockServiceDep,
) -> UserBlockPublic:
    return service.update_block(player[1].id, block_id, data)


@router.delete("/player-blocks/repeating/{block_id}", status_code=204)
def delete_player_block(
    block_id: int, player: DashboardPlayer, service: SoftBlockServiceDep
) -> None:
    service.delete_block(player[1].id, block_id)


@router.post("/player-blocks/busy", status_code=201)
def add_player_busy(
    data: UserBusyCreate, player: DashboardPlayer, service: SoftBlockServiceDep
) -> UserBusyPublic:
    """Add a run of whole local days the player is busy."""
    return service.add_busy(player[1].id, data)


@router.put("/player-blocks/busy/{busy_id}")
def update_player_busy(
    busy_id: int,
    data: UserBusyUpdate,
    player: DashboardPlayer,
    service: SoftBlockServiceDep,
) -> UserBusyPublic:
    return service.update_busy(player[1].id, busy_id, data)


@router.delete("/player-blocks/busy/{busy_id}", status_code=204)
def delete_player_busy(
    busy_id: int, player: DashboardPlayer, service: SoftBlockServiceDep
) -> None:
    service.delete_busy(player[1].id, busy_id)


@router.get("/player-series/{series_id}/free-time")
def get_series_free_time(
    series_id: int,
    request: Request,
    credentials: Credentials,
    user_service: UserServiceDep,
    service: SoftBlockServiceDep,
    start: datetime | None = None,
    end: datetime | None = None,
) -> FreeTimePublic:
    """The hours both players have free, by default across the series' round.

    A player of the series, a captain of either team or an admin reads it. It
    answers shared ranges and their sum, never whose block is whose.
    """
    claims = require_member(request, credentials)
    admin = claims.get("role") == "admin" or claims["sub"] == "admin"
    users = [] if admin else user_service.find_by_discord_id(str(claims["sub"]))
    return service.free_time(
        series_id,
        admin=admin,
        user_id=users[0].id if users else None,
        seats=claim_seats(claims),
        start=start,
        end=end,
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
) -> dict[str, Any]:
    """Update a series that belongs to the authenticated player."""
    # The caller is named before the body is read, so a torn body is answered
    # as the bad request it is and never as an anonymous traceback
    entry = _identity(request, credentials)

    # Handle both form data and JSON
    content_type = request.headers.get("content-type") or ""
    sent: dict[str, Any] = {}
    if "multipart/form-data" in content_type or "x-www-form-urlencoded" in content_type:
        for key, value in (await request.form()).multi_items():
            if not isinstance(value, UploadFile):
                sent.setdefault(key, value)
    else:
        try:
            body = await request.json()
        except ValueError as invalid:
            raise BadRequestError("The body is not valid JSON") from invalid
        if body is not None and not isinstance(body, dict):
            raise BadRequestError("The body must be a JSON object")
        sent = body or {}

    # Only the fields the caller sent, so an untouched one keeps its value
    data = _validated(PlayerSeriesWrite, sent).model_dump(exclude_unset=True)

    # Only the parsing and the identity check above need the event loop
    return await run_in_threadpool(
        player_series.update_player_series,
        series_id,
        data,
        discord_id=str(entry.get("discord_id")),
        discord_tag=entry.get("discord_tag", "Unknown Player"),
        user_service=user_service,
        series_service=series_service,
    )


def _own_series(
    series_service: SeriesService, series_id: int, user_id: int | None
) -> SeriesPublic:
    """The series, for one of its two players."""
    series = series_service.get(series_id)
    if not series:
        raise NotFoundError("series_not_found")
    if user_id not in (series.player1_id, series.player2_id):
        raise ApiError(403, {"error": "not_authorized_for_this_series"})
    return series


@router.post("/player-series/{series_id}/replays/{game_no}/upload-url")
def replay_upload_url(
    series_id: int,
    game_no: int,
    player: DashboardPlayer,
    series_service: SeriesServiceDep,
) -> dict[str, str]:
    """Where the browser puts one game's replay, for either player of the series."""
    _own_series(series_service, series_id, player[1].id)
    return {"url": replays.upload_url(series_id, game_no)}


@router.put("/player-series/{series_id}/replays/{game_no}")
def replace_replay(
    series_id: int,
    game_no: int,
    player: DashboardPlayer,
    series_service: SeriesServiceDep,
) -> SeriesReplayPublic:
    """Point one slot at the file just uploaded. The first report confirms every game itself;
    this replaces one of them afterwards."""
    series = _own_series(series_service, series_id, player[1].id)
    if series.player1_score is None or series.player2_score is None:
        raise BadRequestError("Report the result first")
    played = series.player1_score + series.player2_score
    if not 1 <= game_no <= played:
        raise BadRequestError(f"This series had {played} games")
    rows = replays.confirm(series_id, [game_no], player[1].id)
    return next(row for row in rows if row.game_no == game_no)


def _veto_viewer(
    request: Request,
    credentials: Credentials,
    user_service: UserServiceDep,
) -> tuple[int | None, int | None]:
    """The player behind the request, or null for an admin, who edits either
    side; and the player row to record as the enterer, if the account has one."""
    if credentials is not None:
        claims = require_login(request, credentials)
        if claims.get("role") == "admin" or claims.get("sub") == "admin":
            users = user_service.find_by_discord_id(str(claims["sub"]))
            return None, users[0].id if users else None
    player = dashboard_player(request, credentials, user_service)[1].id
    return player, player


@router.get("/series/{series_id}/games")
def get_series_games(series_id: int) -> list[SeriesGamePublic]:
    """Every game of a series, with the map the season's rules offer for each."""
    return series_games.for_series(series_id)


@router.get("/player-series/{series_id}/veto")
def get_player_series_veto(
    series_id: int,
    user_service: UserServiceDep,
    veto_service: SeriesVetoServiceDep,
    request: Request,
    credentials: Credentials,
) -> SeriesVetoPublic:
    """The map veto board of a series, read by either player or by an admin."""
    viewer, player = _veto_viewer(request, credentials, user_service)
    return veto_service.board(series_id, viewer, player)


@router.put("/player-series/{series_id}/veto")
def set_player_series_veto(
    series_id: int,
    user_service: UserServiceDep,
    veto_service: SeriesVetoServiceDep,
    request: Request,
    credentials: Credentials,
    data: SeriesVetoWrite,
    background: BackgroundTasks,
) -> SeriesVetoPublic:
    """Take the next step of the veto, or take back your own last one. An admin
    enters the step for whichever side is next and takes back any last step.
    The bot's post of the series, if any, is edited after the answer."""
    viewer, entered_by = _veto_viewer(request, credentials, user_service)
    board = veto_service.take(series_id, viewer, data.action, data.map_id, entered_by)
    background.add_task(discord_posts.refresh_series, series_id)
    return board


@router.get("/user-info", response_model=None)
def get_user_info(
    user_service: UserServiceDep,
    request: Request,
    credentials: Credentials,
) -> dict[str, Any]:
    """Get user information (for fantasy team captains who may not be players)."""
    entry = _identity(request, credentials)

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
    entry = _identity(request, credentials)
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
    entry = _identity(request, credentials)

    # Validate required fields
    season_id = data.season_id
    drafted_team_id = data.drafted_team_id
    drafted_race = data.drafted_race
    player_ids = data.player_ids

    if not season_id or not drafted_team_id or not drafted_race:
        raise BadRequestError("missing required fields")
    season_service.refuse_unless_open(season_id)
    if player_ids:
        fantasy_team_service.check_roster(season_id, player_ids)

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
    # An absent grind pick leaves the one on record; a null clears it
    if "grind_team_id" in data.model_fields_set:
        team_data["grind_team_id"] = data.grind_team_id

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
    entry = _identity(request, credentials)
    series = _refuse_started(series_service, data.series_id)

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
    # The season is the series' own, so a bet cannot be tagged onto another one
    bet_payload: dict[str, Any] = {
        "series_id": data.series_id,
        "season_id": series.match.season_id if series and series.match else None,
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
) -> None:
    """Delete a fantasy bet of the identified player."""
    bet = _owned_bet(
        request, credentials, user_service, fantasy_bet_service, bet_id, "delete"
    )
    _refuse_started(series_service, bet.series_id)
    fantasy_bet_service.delete(bet_id)
