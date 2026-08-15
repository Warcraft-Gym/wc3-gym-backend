import io
import logging
import threading
from io import BytesIO
from typing import Annotated, Any

import openpyxl
import pandas as pd
from fastapi import APIRouter, Depends, File, Response, UploadFile
from fastapi.responses import JSONResponse

from app.api.deps import (
    FantasyBetServiceDep,
    FantasyTeamServiceDep,
    MapServiceDep,
    MatchServiceDep,
    SeasonServiceDep,
    SeriesServiceDep,
    TeamServiceDep,
    UserServiceDep,
    require_admin,
)
from app.exceptions import NotFoundError
from app.models.fantasy_bet import FantasyBetCreate, FantasyBetUpdate
from app.models.fantasy_team import FantasyTeamCreate, FantasyTeamUpdate
from app.models.map import MapCreate, MapUpdate
from app.models.match import MatchCreate, MatchUpdate
from app.models.season import SeasonCreate, SeasonUpdate
from app.models.series import SeriesCreate, SeriesUpdate
from app.models.team import TeamCreate, TeamUpdate
from app.models.user import UserCreate
from app.services.fantasy_bets import FantasyBetService
from app.services.fantasy_teams import FantasyTeamService
from app.services.maps import MapService
from app.services.matches import MatchService
from app.services.seasons import SeasonService
from app.services.series import SeriesService
from app.services.teams import TeamService
from app.services.users import UserService
from app.utils.import_util import ImportUtil
from app.utils.query_util import QueryUtil

logger = logging.getLogger(__name__)

router = APIRouter(tags=["import export"])


def _process_import(
    file_bytes: bytes,
    create_new: bool,
    season_service: SeasonService,
    map_service: MapService,
    team_service: TeamService,
    user_service: UserService,
    match_service: MatchService,
    series_service: SeriesService,
    fantasy_team_service: FantasyTeamService,
    fantasy_bet_service: FantasyBetService,
) -> None:
    """
    Helper function to process import. Can be called synchronously or in a thread.

    Args:
        file_bytes: Raw bytes of the Excel file
        create_new: Boolean flag to create new season vs update existing
    """
    try:
        file_stream = io.BytesIO(file_bytes)

        # ===== Step 1: Read Season Metadata =====
        df_season = pd.read_excel(file_stream, sheet_name="Season")
        season_row = df_season.iloc[0]

        season_data = {
            "name": season_row["Name"],
            "number_weeks": int(season_row["Number of Weeks"])
            if not pd.isna(season_row["Number of Weeks"])
            else 0,
            "series_per_week": int(season_row["Series Per Week"])
            if not pd.isna(season_row["Series Per Week"])
            else 0,
            "pick_ban": ImportUtil.isNa(season_row["Pick Ban"]),
            "discordRole": ImportUtil.isNa(season_row["Discord Role"]),
        }

        if not pd.isna(season_row["Start Date"]):
            season_data["start_date"] = pd.to_datetime(season_row["Start Date"]).date()
        if not pd.isna(season_row["End Date"]):
            season_data["end_date"] = pd.to_datetime(season_row["End Date"]).date()

        # Create or update season
        season_id = None
        if create_new:
            # Force create new season
            season = season_service.create_season(SeasonCreate(**season_data))
            season_id = season.id
            logger.info(f"Created new season with ID: {season_id}")
        else:
            # If Season ID is missing, auto-create new season instead of error
            if pd.isna(season_row["ID"]):
                logger.info("Season ID not found in Excel, creating new season")
                season = season_service.create_season(SeasonCreate(**season_data))
                season_id = season.id
                logger.info(f"Created new season with ID: {season_id}")
            else:
                original_season_id = int(season_row["ID"])
                # Check if season exists - handle NotFoundError properly
                try:
                    season_service.get_season(original_season_id)
                    # Season exists, update it
                    season_service.update_season(
                        original_season_id, SeasonUpdate(**season_data)
                    )
                    season_id = original_season_id
                    logger.info(f"Updated existing season with ID: {season_id}")
                except NotFoundError:
                    # Season doesn't exist, create it
                    season = season_service.create_season(SeasonCreate(**season_data))
                    season_id = season.id
                    logger.info(
                        f"Created new season with ID: {season_id} (original ID {original_season_id} not found)"
                    )

        # ID mappings for relationships
        map_id_mapping = {}  # old_id -> new_id
        team_id_mapping = {}
        user_id_mapping = {}
        match_id_mapping = {}

        # ===== Step 2: Import Maps =====
        try:
            df_maps = pd.read_excel(file_stream, sheet_name="Maps")
            for _, row in df_maps.iterrows():
                if pd.isna(row["Name"]):
                    continue
                old_map_id = int(row["ID"]) if not pd.isna(row["ID"]) else None
                map_data = {
                    "name": row["Name"],
                    "shortname": row["Shortname"],
                    "image": ImportUtil.isNa(row["Image URL"]),
                }

                # Check if map exists by shortname
                query = QueryUtil.parseQuery(f"shortname == {map_data['shortname']}")
                if query and query.elementA:
                    existing_maps = map_service.search(query)
                    if existing_maps:
                        map_obj = existing_maps[0]
                        map_service.update_map(map_obj.id, MapUpdate(**map_data))
                    else:
                        map_obj = map_service.create_map(MapCreate(**map_data))

                    if old_map_id:
                        map_id_mapping[old_map_id] = map_obj.id
                    season_service.addMaps(season_id, [map_obj.id])
        except Exception as e:
            logger.warning(f"Maps sheet not found or error: {e}")

        # ===== Step 3: Import Teams =====
        df_teams = pd.read_excel(file_stream, sheet_name="Teams")
        for _, row in df_teams.iterrows():
            if pd.isna(row["Name"]):
                continue
            old_team_id = int(row["ID"]) if not pd.isna(row["ID"]) else None
            team_data = {
                "name": row["Name"],
                "long_name": ImportUtil.isNa(row["Long Name"]),
                "discord_role": ImportUtil.isNa(row["Discord Role"]),
            }

            # Check if team exists by name
            query = QueryUtil.parseQuery(f"name == {team_data['name']}")
            if query and query.elementA:
                existing_teams = team_service.search(query)
                if existing_teams:
                    team = existing_teams[0]
                    team_service.update_team(team.id, TeamUpdate(**team_data))
                else:
                    team = team_service.create_team(TeamCreate(**team_data))

                if old_team_id:
                    team_id_mapping[old_team_id] = team.id

        # Add teams to season
        season_service.addTeams(season_id, list(team_id_mapping.values()))

        # ===== Step 4: Import Players =====
        df_players = pd.read_excel(file_stream, sheet_name="Players")
        for _, row in df_players.iterrows():
            if pd.isna(row["Battle Tag"]):
                continue
            old_user_id = int(row["ID"]) if not pd.isna(row["ID"]) else None
            old_team_id = int(row["Team ID"]) if not pd.isna(row["Team ID"]) else None

            # Build user_data, only including non-null values to avoid overwriting with None
            user_data = {"battleTag": row["Battle Tag"]}

            if not pd.isna(row["Name"]):
                user_data["name"] = row["Name"]
            if not pd.isna(row["Discord Tag"]):
                user_data["discordTag"] = row["Discord Tag"]
            if not pd.isna(row["Discord ID"]):
                user_data["discordId"] = str(row["Discord ID"])
            if not pd.isna(row["Race"]):
                user_data["race"] = row["Race"]
            if not pd.isna(row["MMR"]):
                user_data["mmr"] = int(row["MMR"])
            if not pd.isna(row["Country"]):
                user_data["country"] = row["Country"]
            if not pd.isna(row["Fantasy Tier"]):
                user_data["fantasy_tier"] = int(row["Fantasy Tier"])

            # Check if user exists by battleTag
            query = QueryUtil.parseQuery(f"battleTag == {user_data['battleTag']}")
            if query and query.elementA:
                existing_users = user_service.search(query)
                if existing_users:
                    # User already exists - reuse existing user without updating
                    user = existing_users[0]
                    logger.info(
                        f"Reusing existing user: {user.battleTag} (ID: {user.id})"
                    )
                else:
                    # User doesn't exist - create new user
                    user = user_service.create_user(UserCreate(**user_data))
                    logger.info(f"Created new user: {user.battleTag} (ID: {user.id})")

                if old_user_id:
                    user_id_mapping[old_user_id] = user.id

                # Add player to team for this season
                if old_team_id and old_team_id in team_id_mapping:
                    new_team_id = team_id_mapping[old_team_id]
                    team_service.addPlayers(new_team_id, season_id, [user.id])

        # ===== Step 5: Import Matches =====
        df_matches = pd.read_excel(file_stream, sheet_name="Matches")
        for _, row in df_matches.iterrows():
            if (
                pd.isna(row["Team1 ID"])
                or pd.isna(row["Team2 ID"])
                or pd.isna(row["Playday"])
            ):
                continue
            old_match_id = int(row["ID"]) if not pd.isna(row["ID"]) else None
            old_team1_id = int(row["Team1 ID"])
            old_team2_id = int(row["Team2 ID"])
            old_fixed_map_id = (
                int(row["Fixed Map ID"]) if not pd.isna(row["Fixed Map ID"]) else None
            )

            # Map old IDs to new IDs
            new_team1_id = team_id_mapping.get(old_team1_id)
            new_team2_id = team_id_mapping.get(old_team2_id)
            if not new_team1_id or not new_team2_id:
                logger.warning(
                    f"Skipping match - team IDs not found: {old_team1_id}, {old_team2_id}"
                )
                continue

            match_data = {
                "team1_id": new_team1_id,
                "team2_id": new_team2_id,
                "season_id": season_id,
                "playday": int(row["Playday"]),
                "team1_score": int(row["Team1 Score"])
                if not pd.isna(row["Team1 Score"])
                else None,
                "team2_score": int(row["Team2 Score"])
                if not pd.isna(row["Team2 Score"])
                else None,
                "fixed_map_id": map_id_mapping.get(old_fixed_map_id)
                if old_fixed_map_id
                else None,
                "date_frame": ImportUtil.isNa(row["Date Frame"]),
            }

            # Check if match already exists
            q_string = f"team1_id=={new_team1_id} and team2_id=={new_team2_id} and season_id=={season_id} and playday=={match_data['playday']}"
            query = QueryUtil.parseQuery(q_string)
            if query and query.elementA:
                existing_matches = match_service.search(query)
                if existing_matches:
                    match = existing_matches[0]
                    match_service.update_match(match.id, MatchUpdate(**match_data))
                else:
                    match = match_service.create_match(MatchCreate(**match_data))

                if old_match_id:
                    match_id_mapping[old_match_id] = match.id

        # ===== Step 6: Import Series =====
        df_series = pd.read_excel(file_stream, sheet_name="Series")
        series_id_mapping = {}  # old_id -> new_id
        for _, row in df_series.iterrows():
            if (
                pd.isna(row["Match ID"])
                or pd.isna(row["Player1 ID"])
                or pd.isna(row["Player2 ID"])
            ):
                continue

            old_series_id = int(row["ID"]) if not pd.isna(row["ID"]) else None
            old_match_id = (
                int(row["Match ID"]) if not pd.isna(row["Match ID"]) else None
            )
            old_player1_id = (
                int(row["Player1 ID"]) if not pd.isna(row["Player1 ID"]) else None
            )
            old_player2_id = (
                int(row["Player2 ID"]) if not pd.isna(row["Player2 ID"]) else None
            )
            old_host_player_id = (
                int(row["Host Player ID"])
                if not pd.isna(row["Host Player ID"])
                else old_player1_id
            )

            # Map old IDs to new IDs
            new_match_id = match_id_mapping.get(old_match_id)
            new_player1_id = user_id_mapping.get(old_player1_id)
            new_player2_id = user_id_mapping.get(old_player2_id)
            new_host_player_id = user_id_mapping.get(old_host_player_id)

            if not new_match_id or not new_player1_id or not new_player2_id:
                logger.warning(
                    f"Skipping series - IDs not found: match={old_match_id}, p1={old_player1_id}, p2={old_player2_id}"
                )
                continue

            series_data = {
                "match_id": new_match_id,
                "player1_id": new_player1_id,
                "player2_id": new_player2_id,
                "player1_score": int(row["Player1 Score"])
                if not pd.isna(row["Player1 Score"])
                else None,
                "player2_score": int(row["Player2 Score"])
                if not pd.isna(row["Player2 Score"])
                else None,
                "player1_points": int(row["Player1 Points"])
                if not pd.isna(row["Player1 Points"])
                else None,
                "player2_points": int(row["Player2 Points"])
                if not pd.isna(row["Player2 Points"])
                else None,
                "host_player_id": new_host_player_id
                if new_host_player_id
                else new_player1_id,
                "caster": ImportUtil.isNa(row["Caster"]),
                "is_fantasy_match": bool(row["Is Fantasy Match"])
                if not pd.isna(row["Is Fantasy Match"])
                else False,
            }

            # Parse date_time if present
            if not pd.isna(row["Date Time"]):
                try:
                    series_data["date_time"] = pd.to_datetime(row["Date Time"])
                except Exception:
                    pass

            # Check if series already exists
            q_string = f"match_id=={new_match_id} and player1_id=={new_player1_id} and player2_id=={new_player2_id}"
            query = QueryUtil.parseQuery(q_string)
            if query and query.elementA:
                existing_series = series_service.search(query)
                if existing_series:
                    series_service.update_series(
                        existing_series[0].id, SeriesUpdate(**series_data)
                    )
                    if old_series_id:
                        series_id_mapping[old_series_id] = existing_series[0].id
                else:
                    series = series_service.create_series(SeriesCreate(**series_data))
                    if old_series_id:
                        series_id_mapping[old_series_id] = series.id

        # ===== Step 7: Import Fantasy Teams =====
        fantasy_team_id_mapping = {}  # old_id -> new_id
        try:
            df_fantasy_teams = pd.read_excel(file_stream, sheet_name="Fantasy Teams")
            for _, row in df_fantasy_teams.iterrows():
                if pd.isna(row["Name"]) or pd.isna(row["Captain ID"]):
                    continue

                old_fteam_id = int(row["ID"]) if not pd.isna(row["ID"]) else None
                old_captain_id = (
                    int(row["Captain ID"]) if not pd.isna(row["Captain ID"]) else None
                )
                old_drafted_team_id = (
                    int(row["Drafted Team ID"])
                    if not pd.isna(row["Drafted Team ID"])
                    else None
                )

                new_captain_id = user_id_mapping.get(old_captain_id)
                new_drafted_team_id = (
                    team_id_mapping.get(old_drafted_team_id)
                    if old_drafted_team_id
                    else None
                )

                if not new_captain_id:
                    logger.warning(
                        f"Skipping fantasy team - captain ID not found: {old_captain_id}"
                    )
                    continue

                fteam_data = {
                    "name": row["Name"],
                    "season_id": season_id,
                    "captain_id": new_captain_id,
                    "drafted_team_id": new_drafted_team_id,
                    "drafted_race": ImportUtil.isNa(row["Drafted Race"]),
                    "player_points": int(row["Player Points"])
                    if not pd.isna(row["Player Points"])
                    else 0,
                    "bench_points": int(row["Bench Points"])
                    if not pd.isna(row["Bench Points"])
                    else 0,
                    "team_points": int(row["Team Points"])
                    if not pd.isna(row["Team Points"])
                    else 0,
                    "race_points": int(row["Race Points"])
                    if not pd.isna(row["Race Points"])
                    else 0,
                    "bet_points": int(row["Bet Points"])
                    if not pd.isna(row["Bet Points"])
                    else 0,
                    "total_points": int(row["Total Points"])
                    if not pd.isna(row["Total Points"])
                    else 0,
                }

                # Check if fantasy team exists
                q_string = f"season_id=={season_id} and captain_id=={new_captain_id}"
                query = QueryUtil.parseQuery(q_string)
                if query and query.elementA:
                    existing_fteams = fantasy_team_service.search_fantasy_teams(query)
                    if existing_fteams:
                        fteam = existing_fteams[0]
                        fantasy_team_service.update_fantasy_team(
                            fteam.id, FantasyTeamUpdate(**fteam_data)
                        )
                    else:
                        fteam = fantasy_team_service.create_fantasy_team(
                            FantasyTeamCreate(**fteam_data)
                        )

                    if old_fteam_id:
                        fantasy_team_id_mapping[old_fteam_id] = fteam.id
        except Exception as e:
            logger.warning(f"Fantasy Teams sheet not found or error: {e}")

        # ===== Step 8: Import Fantasy Team Players =====
        try:
            df_fantasy_players = pd.read_excel(
                file_stream, sheet_name="Fantasy Team Players"
            )
            # Group players by fantasy team
            fantasy_team_players = {}
            for _, row in df_fantasy_players.iterrows():
                if pd.isna(row["Fantasy Team ID"]) or pd.isna(row["Player ID"]):
                    continue

                old_fteam_id = int(row["Fantasy Team ID"])
                old_player_id = int(row["Player ID"])

                new_fteam_id = fantasy_team_id_mapping.get(old_fteam_id)
                new_player_id = user_id_mapping.get(old_player_id)

                if new_fteam_id and new_player_id:
                    if new_fteam_id not in fantasy_team_players:
                        fantasy_team_players[new_fteam_id] = []
                    fantasy_team_players[new_fteam_id].append(new_player_id)

            # Add players to fantasy teams
            for fteam_id, player_ids in fantasy_team_players.items():
                fantasy_team_service.addFantasyPlayers(fteam_id, player_ids)
        except Exception as e:
            logger.warning(f"Fantasy Team Players sheet not found or error: {e}")

        # ===== Step 9: Import Fantasy Bets =====
        try:
            df_fantasy_bets = pd.read_excel(file_stream, sheet_name="Fantasy Bets")
            for _, row in df_fantasy_bets.iterrows():
                if (
                    pd.isna(row["Series ID"])
                    or pd.isna(row["User ID"])
                    or pd.isna(row["Winner ID"])
                ):
                    continue

                old_series_id = int(row["Series ID"])
                old_user_id = int(row["User ID"])
                old_winner_id = int(row["Winner ID"])

                new_series_id = series_id_mapping.get(old_series_id)
                new_user_id = user_id_mapping.get(old_user_id)
                new_winner_id = user_id_mapping.get(old_winner_id)

                if not new_series_id or not new_user_id or not new_winner_id:
                    logger.warning(
                        f"Skipping fantasy bet - IDs not found: series={old_series_id}, user={old_user_id}, winner={old_winner_id}"
                    )
                    continue

                fbet_data = {
                    "season_id": season_id,
                    "series_id": new_series_id,
                    "user_id": new_user_id,
                    "winner_id": new_winner_id,
                    "bet_points": int(row["Bet Points"])
                    if not pd.isna(row["Bet Points"])
                    else 0,
                    "bet_result": int(row["Bet Result"])
                    if not pd.isna(row["Bet Result"])
                    else None,
                }

                # Check if bet exists
                q_string = f"series_id=={new_series_id} and user_id=={new_user_id} and winner_id=={new_winner_id}"
                query = QueryUtil.parseQuery(q_string)
                if query and query.elementA:
                    existing_bets = fantasy_bet_service.search_fantasy_bets(query)
                    if existing_bets:
                        fantasy_bet_service.update_fantasy_bet(
                            existing_bets[0].id, FantasyBetUpdate(**fbet_data)
                        )
                    else:
                        fantasy_bet_service.create_fantasy_bet(
                            FantasyBetCreate(**fbet_data)
                        )
        except Exception as e:
            logger.warning(f"Fantasy Bets sheet not found or error: {e}")

        logger.info(f"Background import completed for season: {season_data['name']}")

    except Exception as e:
        logger.error(f"Background import error: {e}")
        import traceback

        logger.error(traceback.format_exc())


# import export endpoints
@router.post("/import", dependencies=[Depends(require_admin)], response_model=None)
def import_season(
    season_service: SeasonServiceDep,
    map_service: MapServiceDep,
    team_service: TeamServiceDep,
    user_service: UserServiceDep,
    match_service: MatchServiceDep,
    series_service: SeriesServiceDep,
    fantasy_team_service: FantasyTeamServiceDep,
    fantasy_bet_service: FantasyBetServiceDep,
    file: Annotated[UploadFile | None, File()] = None,
    create_new: str = "false",
    background: str = "false",
) -> JSONResponse | dict[str, Any]:
    """Import complete season data from Excel.

    Imports ALL season data (season, maps, teams, players, matches, series)
    from Excel file.
    """
    if file is None:
        return JSONResponse({"error": "No file part"}, status_code=400)

    create_new = create_new.lower() == "true"
    background = background.lower() == "true"

    if file.filename == "" or not file.filename.endswith((".xlsx", ".xls")):
        return JSONResponse(
            {"error": "No selected file or invalid file type"}, status_code=400
        )

    # Read file into memory
    file_bytes = file.file.read()

    services = (
        season_service,
        map_service,
        team_service,
        user_service,
        match_service,
        series_service,
        fantasy_team_service,
        fantasy_bet_service,
    )

    # If background mode, spawn thread and return immediately
    if background:
        thread = threading.Thread(
            target=_process_import,
            args=(file_bytes, create_new, *services),
            daemon=True,
        )
        thread.start()
        logger.info("Import started in background thread")
        return JSONResponse(
            {"message": "Import started in background"}, status_code=202
        )

    # Otherwise, process synchronously
    _process_import(file_bytes, create_new, *services)

    # Read season name for response
    temp_stream = io.BytesIO(file_bytes)
    df_season = pd.read_excel(temp_stream, sheet_name="Season")
    season_row = df_season.iloc[0]
    season_name = season_row["Name"]

    # Get season ID (either from Excel or newly created)
    if pd.isna(season_row["ID"]):
        # New season was created, get it by name
        query = QueryUtil.parseQuery(f"name == {season_name}")
        if query and query.elementA:
            seasons = season_service.search(query)
            season_id = seasons[0].id if seasons else None
    else:
        season_id = int(season_row["ID"])

    return {
        "message": "Season imported successfully",
        "season_id": season_id,
        "season_name": season_name,
    }


@router.post("/export", dependencies=[Depends(require_admin)])
def export_season(
    season_service: SeasonServiceDep,
    team_service: TeamServiceDep,
    match_service: MatchServiceDep,
    series_service: SeriesServiceDep,
    fantasy_team_service: FantasyTeamServiceDep,
    fantasy_bet_service: FantasyBetServiceDep,
    season_id: str | None = None,
) -> Response:
    """Export complete season data for migration.

    Export an Excel file with ALL season data (season, maps, teams, players,
    matches, series).
    """
    season_id = int(season_id)
    season = season_service.get_season(season_id)
    if not season:
        raise NotFoundError(f"Season not found by id: {season_id}")

    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)

    # ===== Sheet 1: Season Metadata =====
    season_sheet = workbook.create_sheet(title="Season")
    season_sheet.append(
        [
            "ID",
            "Name",
            "Number of Weeks",
            "Series Per Week",
            "Pick Ban",
            "Start Date",
            "End Date",
            "Discord Role",
        ]
    )
    season_sheet.append(
        [
            season.id,
            season.name,
            season.number_weeks,
            season.series_per_week,
            season.pick_ban if season.pick_ban else "",
            season.start_date.strftime("%Y-%m-%d") if season.start_date else "",
            season.end_date.strftime("%Y-%m-%d") if season.end_date else "",
            season.discordRole if season.discordRole else "",
        ]
    )

    # ===== Sheet 2: Maps =====
    maps_sheet = workbook.create_sheet(title="Maps")
    maps_sheet.append(["ID", "Name", "Shortname", "Image URL"])
    if season.maps:
        for map_obj in season.maps:
            maps_sheet.append(
                [
                    map_obj.id,
                    map_obj.name,
                    map_obj.shortname,
                    map_obj.image if map_obj.image else "",
                ]
            )

    # ===== Sheet 3: Teams =====
    teams_sheet = workbook.create_sheet(title="Teams")
    teams_sheet.append(["ID", "Name", "Long Name", "Discord Role", "Icon URL"])
    season_teams = team_service.get_teams_season(season_id)
    for team in season_teams:
        teams_sheet.append(
            [
                team.id,
                team.name,
                team.long_name if team.long_name else "",
                team.discord_role if team.discord_role else "",
                team.icon_url if hasattr(team, "icon_url") and team.icon_url else "",
            ]
        )

    # ===== Sheet 4: Players =====
    players_sheet = workbook.create_sheet(title="Players")
    players_sheet.append(
        [
            "ID",
            "Name",
            "Battle Tag",
            "Discord Tag",
            "Discord ID",
            "Race",
            "MMR",
            "Country",
            "Fantasy Tier",
            "Team ID",
        ]
    )
    for team in season_teams:
        players = team.player_by_season.get(season_id, [])
        for user in players:
            race_value = user.race.value if hasattr(user.race, "value") else user.race
            country_value = (
                user.country.value if hasattr(user.country, "value") else user.country
            )
            players_sheet.append(
                [
                    user.id,
                    user.name,
                    user.battleTag,
                    user.discordTag,
                    user.discordId if user.discordId else "",
                    race_value,
                    user.mmr if user.mmr else "",
                    country_value if country_value else "",
                    user.fantasy_tier if user.fantasy_tier else "",
                    team.id,
                ]
            )

    # ===== Sheet 5: Matches =====
    matches_sheet = workbook.create_sheet(title="Matches")
    matches_sheet.append(
        [
            "ID",
            "Team1 ID",
            "Team2 ID",
            "Season ID",
            "Playday",
            "Team1 Score",
            "Team2 Score",
            "Fixed Map ID",
            "Date Frame",
        ]
    )
    q_string = f"season_id=={season_id}"
    query = QueryUtil.parseQuery(q_string)
    if query and query.elementA:
        all_matches = match_service.search(query)
        for match in all_matches:
            matches_sheet.append(
                [
                    match.id,
                    match.team1.id,
                    match.team2.id,
                    match.season.id,
                    match.playday,
                    match.team1_score if match.team1_score else "",
                    match.team2_score if match.team2_score else "",
                    match.fixed_map.id if match.fixed_map else "",
                    match.date_frame if match.date_frame else "",
                ]
            )

    # ===== Sheet 6: Series =====
    series_sheet = workbook.create_sheet(title="Series")
    series_sheet.append(
        [
            "ID",
            "Match ID",
            "Player1 ID",
            "Player2 ID",
            "Player1 Score",
            "Player2 Score",
            "Player1 Points",
            "Player2 Points",
            "Host Player ID",
            "Date Time",
            "Caster",
            "Is Fantasy Match",
        ]
    )
    for match in all_matches if "all_matches" in locals() else []:
        q_string = f"match_id=={match.id}"
        query = QueryUtil.parseQuery(q_string)
        if query and query.elementA:
            series_list = series_service.search(query)
            for series in series_list:
                date_time_str = (
                    series.date_time.strftime("%Y-%m-%d %H:%M:%S")
                    if series.date_time
                    else ""
                )
                series_sheet.append(
                    [
                        series.id,
                        series.match.id,
                        series.player1.id,
                        series.player2.id,
                        series.player1_score
                        if series.player1_score is not None
                        else "",
                        series.player2_score
                        if series.player2_score is not None
                        else "",
                        series.player1_points if series.player1_points else "",
                        series.player2_points if series.player2_points else "",
                        series.host_player_id,
                        date_time_str,
                        series.caster if series.caster else "",
                        series.is_fantasy_match if series.is_fantasy_match else False,
                    ]
                )

    # ===== Sheet 7: Fantasy Teams =====
    fantasy_teams_sheet = workbook.create_sheet(title="Fantasy Teams")
    fantasy_teams_sheet.append(
        [
            "ID",
            "Name",
            "Season ID",
            "Captain ID",
            "Drafted Team ID",
            "Drafted Race",
            "Player Points",
            "Bench Points",
            "Team Points",
            "Race Points",
            "Bet Points",
            "Total Points",
        ]
    )
    q_string = f"season_id=={season_id}"
    query = QueryUtil.parseQuery(q_string)
    if query and query.elementA:
        fantasy_teams = fantasy_team_service.search_fantasy_teams(query)
        for fteam in fantasy_teams:
            drafted_race_value = (
                fteam.drafted_race.value
                if hasattr(fteam.drafted_race, "value")
                else fteam.drafted_race
            )
            fantasy_teams_sheet.append(
                [
                    fteam.id,
                    fteam.name,
                    fteam.season_id,
                    fteam.captain_id,
                    fteam.drafted_team_id if fteam.drafted_team_id else "",
                    drafted_race_value if drafted_race_value else "",
                    fteam.player_points if fteam.player_points else 0,
                    fteam.bench_points if fteam.bench_points else 0,
                    fteam.team_points if fteam.team_points else 0,
                    fteam.race_points if fteam.race_points else 0,
                    fteam.bet_points if fteam.bet_points else 0,
                    fteam.total_points if fteam.total_points else 0,
                ]
            )

    # ===== Sheet 8: Fantasy Team Players (many-to-many) =====
    fantasy_players_sheet = workbook.create_sheet(title="Fantasy Team Players")
    fantasy_players_sheet.append(["Fantasy Team ID", "Player ID"])
    for fteam in fantasy_teams if "fantasy_teams" in locals() else []:
        if fteam.drafted_players:
            for player in fteam.drafted_players:
                fantasy_players_sheet.append([fteam.id, player.id])

    # ===== Sheet 9: Fantasy Bets =====
    fantasy_bets_sheet = workbook.create_sheet(title="Fantasy Bets")
    fantasy_bets_sheet.append(
        [
            "ID",
            "Season ID",
            "Series ID",
            "User ID",
            "Winner ID",
            "Bet Points",
            "Bet Result",
        ]
    )
    if query and query.elementA:
        fantasy_bets = fantasy_bet_service.search_fantasy_bets(query)
        for fbet in fantasy_bets:
            fantasy_bets_sheet.append(
                [
                    fbet.id,
                    fbet.season_id,
                    fbet.series_id,
                    fbet.user_id,
                    fbet.winner_id,
                    fbet.bet_points,
                    fbet.bet_result if fbet.bet_result else "",
                ]
            )

    excel_stream = BytesIO()
    workbook.save(excel_stream)
    excel_stream.seek(0)

    download_name = f"{season.name.replace(' ', '_')}_export.xlsx"
    return Response(
        content=excel_stream.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


# import export endpoints
@router.post("/fantasy/import/teams", response_model=None)
def import_fantasy_teams(
    season_service: SeasonServiceDep,
    user_service: UserServiceDep,
    team_service: TeamServiceDep,
    fantasy_team_service: FantasyTeamServiceDep,
    file: Annotated[UploadFile | None, File()] = None,
    season_id: str | None = None,
    season_name: str | None = None,
) -> JSONResponse | dict[str, Any] | None:
    """Import a xlsx with the information for a GNL fantasy season.

    Updates the database based on the import sheet.
    """
    if file is None:
        return JSONResponse({"error": "No file part"}, status_code=400)

    season_id = int(season_id) if season_id else None

    if not season_id:
        if season_name:
            query = QueryUtil.parseQuery("name == " + season_name)
            if not query or not query.elementA:
                raise Exception(f"No valid query found: {'name == ' + season_name}")
            found_seasons = season_service.search(query)
            if not found_seasons:
                raise Exception(f"Season could not be found by name: {season_name}")
            else:
                season_id = found_seasons[0].id
        else:
            raise Exception(
                "Missing Season parameter, either season_id or season name is required"
            )

    if file.filename == "":
        return JSONResponse({"error": "No selected file"}, status_code=400)
    if file and file.filename.endswith((".xlsx", ".xls")):
        file_stream = io.BytesIO(file.file.read())

        # Load the Google Sheet into a DataFrame
        df_teams = pd.read_excel(file_stream, sheet_name="Formatted Responses")

        for index, row in df_teams.iterrows():
            if not ImportUtil.isNa(row.iloc[0]):
                continue
            if not ImportUtil.isNa(row.iloc[1]):
                raise Exception(f"Team without captain: {row.iloc[0]}")
            query = QueryUtil.parseQuery("discordTag == " + row.iloc[1])
            if not query or not query.elementA:
                raise Exception(
                    f"No valid query found: {'discordTag == ' + row.iloc[1]}"
                )
            users = user_service.search(query)
            captain = None
            if not users:
                logger.debug(
                    f"No user found for discordTag {row.iloc[1]}: create dummy user for fantasy league"
                )
                user_data = {
                    "name": row.iloc[1],
                    "battleTag": "Fantasy_User",
                    "discordTag": row.iloc[1],
                    "race": "Random",
                }
                captain = user_service.create_user(UserCreate(**user_data))
            elif len(users) != 1:
                raise Exception(
                    f"No or multiple users found for captain[{row.iloc[1]}]: {users}"
                )
            else:
                captain = users[0]

            if not ImportUtil.isNa(row.iloc[10]):
                raise Exception(f"No GNL team defined for team: {row.iloc[0]}")
            query = QueryUtil.parseQuery("name==" + row.iloc[10])
            if not query or not query.elementA:
                raise Exception(f"No valid query found: {'name == ' + row.iloc[10]}")
            found_teams = team_service.search(query)
            if not found_teams or len(found_teams) != 1:
                raise Exception(
                    f"No or multiple teams found for gnl team name[{row.iloc[10]} ]: {found_teams}"
                )
            team = found_teams[0]

            if not ImportUtil.isNa(row.iloc[11]):
                raise Exception(f"No Race defined for team: {row.iloc[11]}")

            team_data = {
                "name": ImportUtil.isNa(row.iloc[0]),
                "captain_id": captain.id,
                "season_id": season_id,
                "drafted_team_id": team.id,
                "drafted_race": ImportUtil.getRaceEnumString(row.iloc[11]),
            }

            fantasy_team = None
            fteam_q_string = f"season_id=={season_id} and captain_id=={captain.id}"
            fteam_query = QueryUtil.parseQuery(fteam_q_string)
            if not query or not query.elementA:
                raise Exception(f"No valid query found: {fteam_q_string}")
            found_teams = fantasy_team_service.search_fantasy_teams(fteam_query)
            if found_teams and len(found_teams) == 1:
                team = found_teams[0]
                fantasy_team = fantasy_team_service.update_fantasy_team(
                    team.id, FantasyTeamUpdate(**team_data)
                )
            elif len(found_teams) > 1:
                raise Exception(f"More than one bet found by search: {fteam_q_string}")
            else:
                fantasy_team = fantasy_team_service.create_fantasy_team(
                    FantasyTeamCreate(**team_data)
                )

            players = []
            found_players = {}
            for player in row[2:10]:
                if not player:
                    raise Exception(f"Player missing for team: {row.iloc[0]}")
                found_player_id = found_players.get(player)
                if found_player_id:
                    players.append(found_player_id)
                else:
                    query = QueryUtil.parseQuery("name == " + player)
                    if not query or not query.elementA:
                        raise Exception(f"No valid query found: {'name == ' + player}")
                    users = user_service.search(query)
                    if not users or len(users) != 1:
                        raise Exception(f"Could not find player by name: {player}")
                    found_player = users[0]
                    found_players[found_player.name] = found_player.id
                    players.append(found_player.id)
            removePlayers = []
            for existingPlayer in fantasy_team.drafted_players:
                if not existingPlayer.id in players:
                    removePlayers.append(existingPlayer.id)

            fantasy_team_service.removeFantasyPlayers(fantasy_team.id, removePlayers)
            fantasy_team_service.addFantasyPlayers(fantasy_team.id, players)

        return {"message": "File uploaded successfully and data inserted into database"}
    else:
        return JSONResponse({"error": "File type not allowed"}, status_code=400)


@router.post("/fantasy/import/bets", response_model=None)
def import_fantasy_bets(
    season_service: SeasonServiceDep,
    user_service: UserServiceDep,
    match_service: MatchServiceDep,
    series_service: SeriesServiceDep,
    fantasy_bet_service: FantasyBetServiceDep,
    file: Annotated[UploadFile | None, File()] = None,
    season_id: str | None = None,
    season_name: str | None = None,
) -> JSONResponse | dict[str, Any] | None:
    """Import a xlsx with the information for a GNL fantasy season.

    Updates the database based on the import sheet.
    """
    if file is None:
        return JSONResponse({"error": "No file part"}, status_code=400)

    season_id = int(season_id) if season_id else None

    if not season_id:
        if season_name:
            query = QueryUtil.parseQuery("name == " + season_name)
            if not query or not query.elementA:
                raise Exception(f"No valid query found: {'name == ' + season_name}")
            found_seasons = season_service.search(query)
            if not found_seasons:
                raise Exception(f"Season could not be found by name: {season_name}")
            else:
                season_id = found_seasons[0].id
        else:
            raise Exception(
                "Missing Season parameter, either season_id or season name is required"
            )

    if file.filename == "":
        return JSONResponse({"error": "No selected file"}, status_code=400)
    if file and file.filename.endswith((".xlsx", ".xls")):
        file_stream = io.BytesIO(file.file.read())

        df_bet_match = pd.read_excel(file_stream, sheet_name="Betting Matches")
        for index, row in df_bet_match.iterrows():
            if not ImportUtil.isNa(row.iloc[0]):
                continue
            week = row.iloc[0]
            q_string = f"playday=={week} and season_id=={season_id}"
            query = QueryUtil.parseQuery(q_string)
            if not query or not query.elementA:
                raise Exception(f"No valid query found: {q_string}")
            matches = match_service.search(query)
            query = QueryUtil.parseQuery("name == " + row.iloc[1])
            if not query or not query.elementA:
                raise Exception(f"No valid query found: {'name == ' + row.iloc[1]}")
            users = user_service.search(query)
            if not users or len(users) != 1:
                raise Exception(
                    f"No or multiple users found for bet player[{row.iloc[1]}]: {users}"
                )
            player1 = users[0]
            query = QueryUtil.parseQuery("name == " + row.iloc[2])
            if not query or not query.elementA:
                raise Exception(f"No valid query found: {'name == ' + row.iloc[2]}")
            users = user_service.search(query)
            if not users or len(users) != 1:
                raise Exception(
                    f"No or multiple users found for bet player[{row.iloc[1]}]: {users}"
                )
            player2 = users[0]
            series = None
            if matches:
                for match in matches:
                    series_q_string = f"player1_id == {player1.id} and player2_id == {player2.id} and match_id == {match.id} or player1_id == {player2.id} and player2_id == {player1.id} and match_id == {match.id}"
                    series_query = QueryUtil.parseQuery(series_q_string)
                    if not query or not query.elementA:
                        raise Exception(f"No valid query found: {series_q_string}")
                    found_series = series_service.search(series_query)
                    if not found_series or len(found_series) != 1:
                        continue
                    series = found_series[0]
                    break
                if not series:
                    raise Exception(
                        f"Could not identfy series for player: {row.iloc[1]}!"
                    )
            series_service.update_series(series.id, SeriesUpdate(is_fantasy_match=True))

        # Load the Google Sheet into a DataFrame
        df_bets = pd.read_excel(file_stream, sheet_name="Bets")
        for index, row in df_bets.iterrows():
            if not ImportUtil.isNa(row.iloc[0]):
                continue
            if not ImportUtil.isNa(row.iloc[0]):
                raise Exception(f"Week not defined: {row.iloc[0]}")
            playday = row.iloc[0]

            if not ImportUtil.isNa(row.iloc[1]):
                raise Exception(f"Captain not defined: {row.iloc[1]}")
            query = QueryUtil.parseQuery("discordTag == " + row.iloc[1])
            if not query or not query.elementA:
                raise Exception(
                    f"No valid query found: {'discordTag == ' + row.iloc[1]}"
                )
            users = user_service.search(query)
            if not users or len(users) != 1:
                raise Exception(
                    f"No or multiple users found for captain[{row.iloc[1]}]: {users}"
                )
            captain = users[0]

            if not ImportUtil.isNa(row.iloc[2]):
                raise Exception(f"Bet Player not defined: {row.iloc[2]}")

            query = QueryUtil.parseQuery("name == " + row.iloc[2])
            if not query or not query.elementA:
                raise Exception(f"No valid query found: {'name == ' + row.iloc[2]}")
            users = user_service.search(query)
            if not users or len(users) != 1:
                raise Exception(
                    f"No or multiple users found for bet player[{row.iloc[2]}]: {users}"
                )
            bet_player = users[0]

            q_string = f"playday=={playday} and season_id=={season_id}"
            query = QueryUtil.parseQuery(q_string)
            if not query or not query.elementA:
                raise Exception(f"No valid query found: {q_string}")
            matches = match_service.search(query)
            series = None
            if matches:
                for match in matches:
                    series_q_string = f"player1_id == {bet_player.id} and is_fantasy_match == True and match_id == {match.id} or player2_id == {bet_player.id} and is_fantasy_match == True and match_id == {match.id}"
                    series_query = QueryUtil.parseQuery(series_q_string)
                    if not query or not query.elementA:
                        raise Exception(f"No valid query found: {series_q_string}")
                    found_series = series_service.search(series_query)
                    if not found_series or len(found_series) != 1:
                        continue
                    series = found_series[0]
                    break
            if not series:
                raise Exception(
                    f"Could not identfy series for player: {bet_player.name}!"
                )

            if not ImportUtil.isNa(row.iloc[3]):
                raise Exception(f"Bet Points not defined: {row.iloc[3]}")

            bet_data = {
                "season_id": season_id,
                "series_id": series.id,
                "user_id": captain.id,
                "winner_id": bet_player.id,
                "bet_points": row.iloc[3],
            }

            bet_q_string = f"series_id=={series.id} and user_id=={captain.id} and winner_id=={bet_player.id}"
            bet_query = QueryUtil.parseQuery(bet_q_string)
            if not query or not query.elementA:
                raise Exception(f"No valid query found: {bet_q_string}")
            found_bets = fantasy_bet_service.search_fantasy_bets(bet_query)
            if found_bets and len(found_bets) == 1:
                bet = found_bets[0]
                fantasy_bet_service.update_fantasy_bet(
                    bet.id, FantasyBetUpdate(**bet_data)
                )
            elif len(found_bets) > 1:
                raise Exception(f"More than one bet found by search: {bet_q_string}")
            else:
                fantasy_bet_service.create_fantasy_bet(FantasyBetCreate(**bet_data))

        return {"message": "File uploaded successfully and data inserted into database"}
    else:
        return JSONResponse({"error": "File type not allowed"}, status_code=400)
