"""The season import pipeline.

Reads an exported season workbook and writes the rows it holds. The
caller supplies the services, so this module opens no session of its own.
"""

import io
import logging

import pandas as pd

from app.core.exceptions import NotFoundError
from app.core.query import QueryUtil
from app.models.enums import Race
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

logger = logging.getLogger(__name__)


def cell_value[T](value: T) -> T | None:
    """Read a spreadsheet cell. An empty cell reads as None, not as NaN."""
    if pd.isna(value):
        return None
    return value


def process_import(
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
    """Read the workbook and write the season it holds.

    A failure raises, so the caller decides what the client reads.

    Args:
        file_bytes: Raw bytes of the Excel file
        create_new: Boolean flag to create new season vs update existing
    """
    # sheet_name=None reads every sheet, so the workbook is parsed once
    sheets = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None)

    # ===== Step 1: Read Season Metadata =====
    df_season = sheets["Season"]
    season_row = df_season.iloc[0]

    season_data = {
        "name": season_row["Name"],
        "number_weeks": int(season_row["Number of Weeks"])
        if not pd.isna(season_row["Number of Weeks"])
        else 0,
        "series_per_week": int(season_row["Series Per Week"])
        if not pd.isna(season_row["Series Per Week"])
        else 0,
        "pick_ban": cell_value(season_row["Pick Ban"]),
        "discordRole": cell_value(season_row["Discord Role"]),
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
        df_maps = sheets["Maps"]
        for _, row in df_maps.iterrows():
            if pd.isna(row["Name"]):
                continue
            old_map_id = int(row["ID"]) if not pd.isna(row["ID"]) else None
            map_data = {
                "name": row["Name"],
                "shortname": row["Shortname"],
                "image": cell_value(row["Image URL"]),
            }

            # Check if map exists by shortname
            existing_maps = map_service.find_by_shortname(map_data["shortname"])
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
    df_teams = sheets["Teams"]
    for _, row in df_teams.iterrows():
        if pd.isna(row["Name"]):
            continue
        old_team_id = int(row["ID"]) if not pd.isna(row["ID"]) else None
        team_data = {
            "name": row["Name"],
            "long_name": cell_value(row["Long Name"]),
            "discord_role": cell_value(row["Discord Role"]),
        }

        # Check if team exists by name
        existing_teams = team_service.find_by_name(team_data["name"])
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
    df_players = sheets["Players"]
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
        existing_users = user_service.find_by_battle_tag(user_data["battleTag"])
        if existing_users:
            # User already exists - reuse existing user without updating
            user = existing_users[0]
            logger.info(f"Reusing existing user: {user.battleTag} (ID: {user.id})")
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
    df_matches = sheets["Matches"]
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
            "fixed_map_id": map_id_mapping.get(old_fixed_map_id)
            if old_fixed_map_id
            else None,
            "date_frame": cell_value(row["Date Frame"]),
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
    df_series = sheets["Series"]
    series_id_mapping = {}  # old_id -> new_id
    # One statement for the series already stored, so the loop needs none
    stored_series = series_service.series_ids_of_matches(match_id_mapping.values())
    for _, row in df_series.iterrows():
        if (
            pd.isna(row["Match ID"])
            or pd.isna(row["Player1 ID"])
            or pd.isna(row["Player2 ID"])
        ):
            continue

        old_series_id = int(row["ID"]) if not pd.isna(row["ID"]) else None
        old_match_id = int(row["Match ID"]) if not pd.isna(row["Match ID"]) else None
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
            "host_player_id": new_host_player_id
            if new_host_player_id
            else new_player1_id,
            "caster": cell_value(row["Caster"]),
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

        key = (new_match_id, new_player1_id, new_player2_id)
        stored = stored_series.get(key)
        if stored:
            new_series_id = stored[0]
            series_service.update_series(new_series_id, SeriesUpdate(**series_data))
        else:
            new_series_id = series_service.create_series(SeriesCreate(**series_data)).id
            # A later row of the same file must find the series this one made
            stored_series[key] = [new_series_id]
        if old_series_id:
            series_id_mapping[old_series_id] = new_series_id

    # ===== Step 7: Import Fantasy Users =====
    # Captains and bettors on no roster, mapped before the sheets that name them
    df_fantasy_users = sheets.get("Fantasy Users")
    if df_fantasy_users is not None:
        for _, row in df_fantasy_users.iterrows():
            if pd.isna(row["ID"]) or pd.isna(row["Battle Tag"]):
                continue
            old_user_id = int(row["ID"])
            if old_user_id in user_id_mapping:
                continue

            battle_tag = row["Battle Tag"]
            existing_users = user_service.find_by_battle_tag(battle_tag)
            if existing_users:
                user = existing_users[0]
                logger.info(f"Reusing existing user: {user.battleTag} (ID: {user.id})")
            else:
                user_data = {
                    "battleTag": battle_tag,
                    # A fantasy user plays no series, and the sheet carries no race
                    "race": Race.RANDOM,
                    "name": cell_value(row["Name"]) or battle_tag,
                    "discordTag": cell_value(row["Discord Tag"]) or "",
                    "discordId": str(row["Discord ID"])
                    if not pd.isna(row["Discord ID"])
                    else "",
                }
                user = user_service.create_user(UserCreate(**user_data))
                logger.info(
                    f"Created new fantasy user: {user.battleTag} (ID: {user.id})"
                )

            user_id_mapping[old_user_id] = user.id

    # ===== Step 8: Import Fantasy Teams =====
    fantasy_team_id_mapping = {}  # old_id -> new_id
    try:
        df_fantasy_teams = sheets["Fantasy Teams"]
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
                "drafted_race": cell_value(row["Drafted Race"]),
            }

            # Check if fantasy team exists
            q_string = f"season_id=={season_id} and captain_id=={new_captain_id}"
            query = QueryUtil.parseQuery(q_string)
            if query and query.elementA:
                existing_fteams, _ = fantasy_team_service.search_fantasy_teams(query)
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

    # ===== Step 9: Import Fantasy Team Players =====
    try:
        df_fantasy_players = sheets["Fantasy Team Players"]
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

    # ===== Step 10: Import Fantasy Bets =====
    try:
        df_fantasy_bets = sheets["Fantasy Bets"]
        # One statement for the bets already stored, so the loop needs none
        stored_bets = fantasy_bet_service.bet_ids_of_season(season_id)
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
            }

            key = (new_series_id, new_user_id, new_winner_id)
            stored = stored_bets.get(key)
            if stored:
                fantasy_bet_service.update_fantasy_bet(
                    stored[0], FantasyBetUpdate(**fbet_data)
                )
            else:
                bet = fantasy_bet_service.create_fantasy_bet(
                    FantasyBetCreate(**fbet_data)
                )
                # A later row of the same file must find the bet this one made
                stored_bets[key] = [bet.id]
    except Exception as e:
        logger.warning(f"Fantasy Bets sheet not found or error: {e}")

    logger.info(f"Import completed for season: {season_data['name']}")
