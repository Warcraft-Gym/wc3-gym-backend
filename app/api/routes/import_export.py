import io
import logging
from io import BytesIO
from typing import Annotated, Any

import openpyxl
import pandas as pd
from fastapi import APIRouter, Depends, File, Response, UploadFile

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
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.query import QueryUtil
from app.models.enums import Race
from app.models.fantasy_bet import FantasyBetCreate, FantasyBetUpdate
from app.models.fantasy_team import FantasyTeamCreate, FantasyTeamUpdate
from app.models.responses import Message
from app.models.series import SeriesUpdate
from app.models.user import UserCreate
from app.services.season_import import cell_value, process_import

logger = logging.getLogger(__name__)

router = APIRouter(tags=["import export"])

BET_PAGE = 500  # how many bets the export reads per statement


# import export endpoints
@router.post("/import", dependencies=[Depends(require_admin)])
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
) -> dict[str, Any]:
    """Import complete season data from Excel.

    Imports ALL season data (season, maps, teams, players, matches, series)
    from Excel file.
    """
    if file is None:
        raise BadRequestError("No file part")

    create_new = create_new.lower() == "true"

    if file.filename == "" or not file.filename.endswith((".xlsx", ".xls")):
        raise BadRequestError("No selected file or invalid file type")

    # Read file into memory
    file_bytes = file.file.read()

    process_import(
        file_bytes,
        create_new,
        season_service,
        map_service,
        team_service,
        user_service,
        match_service,
        series_service,
        fantasy_team_service,
        fantasy_bet_service,
    )

    # Read season name for response
    temp_stream = io.BytesIO(file_bytes)
    df_season = pd.read_excel(temp_stream, sheet_name="Season")
    season_row = df_season.iloc[0]
    season_name = season_row["Name"]

    # Get season ID (either from Excel or newly created)
    if pd.isna(season_row["ID"]):
        # New season was created, get it by name
        seasons = season_service.find_by_name(season_name)
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
    season_id: int,
) -> Response:
    """Export one season as an Excel workbook of nine sheets.

    The workbook holds the season row, its maps, teams, rostered players,
    matches, series, fantasy teams, fantasy team players and fantasy bets.
    """
    # get_season raises NotFoundError, which answers 404
    season = season_service.get_season(season_id)

    # write_only keeps one row in memory at a time instead of the whole sheet
    workbook = openpyxl.Workbook(write_only=True)

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
        fantasy_teams, _ = fantasy_team_service.search_fantasy_teams(query)
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
        # A season holds the most bets of anything here, so it is read by page
        offset = 0
        while True:
            page, _ = fantasy_bet_service.search_fantasy_bets(
                query, limit=BET_PAGE, offset=offset
            )
            for fbet in page:
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
            if len(page) < BET_PAGE:
                break
            offset += BET_PAGE

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
@router.post("/fantasy/import/teams", dependencies=[Depends(require_admin)])
def import_fantasy_teams(
    season_service: SeasonServiceDep,
    user_service: UserServiceDep,
    team_service: TeamServiceDep,
    fantasy_team_service: FantasyTeamServiceDep,
    file: Annotated[UploadFile | None, File()] = None,
    season_id: str | None = None,
    season_name: str | None = None,
) -> Message:
    """Import a xlsx with the information for a GNL fantasy season.

    Updates the database based on the import sheet.
    """
    if file is None:
        raise BadRequestError("No file part")

    season_id = int(season_id) if season_id else None

    if not season_id:
        if season_name:
            found_seasons = season_service.find_by_name(season_name)
            if not found_seasons:
                raise NotFoundError(f"Season could not be found by name: {season_name}")
            else:
                season_id = found_seasons[0].id
        else:
            raise BadRequestError(
                "Missing Season parameter, either season_id or season name is required"
            )

    if file.filename == "":
        raise BadRequestError("No selected file")
    if file and file.filename.endswith((".xlsx", ".xls")):
        file_stream = io.BytesIO(file.file.read())

        # Load the Google Sheet into a DataFrame
        df_teams = pd.read_excel(file_stream, sheet_name="Formatted Responses")

        for index, row in df_teams.iterrows():
            if not cell_value(row.iloc[0]):
                continue
            if not cell_value(row.iloc[1]):
                raise BadRequestError(f"Team without captain: {row.iloc[0]}")
            users = user_service.find_by_discord_tag(row.iloc[1])
            captain = None
            if not users:
                logger.debug(
                    f"No user found for discordTag {row.iloc[1]}: create dummy user for fantasy league"
                )
                user_data = {
                    "name": row.iloc[1],
                    "battleTag": "Fantasy_User",
                    "discordTag": row.iloc[1],
                    "race": Race.RANDOM,
                }
                captain = user_service.create_user(UserCreate(**user_data))
            elif len(users) != 1:
                raise BadRequestError(
                    f"No or multiple users found for captain[{row.iloc[1]}]: {users}"
                )
            else:
                captain = users[0]

            if not cell_value(row.iloc[10]):
                raise BadRequestError(f"No GNL team defined for team: {row.iloc[0]}")
            found_teams = team_service.find_by_name(row.iloc[10])
            if not found_teams or len(found_teams) != 1:
                raise BadRequestError(
                    f"No or multiple teams found for gnl team name[{row.iloc[10]} ]: {found_teams}"
                )
            team = found_teams[0]

            if not cell_value(row.iloc[11]):
                raise BadRequestError(f"No Race defined for team: {row.iloc[11]}")

            try:
                drafted_race = Race.from_text(str(row.iloc[11]))
            except ValueError as error:
                raise BadRequestError(str(error)) from error

            team_data = {
                "name": cell_value(row.iloc[0]),
                "captain_id": captain.id,
                "season_id": season_id,
                "drafted_team_id": team.id,
                "drafted_race": drafted_race,
            }

            fantasy_team = None
            fteam_q_string = f"season_id=={season_id} and captain_id=={captain.id}"
            fteam_query = QueryUtil.parseQuery(fteam_q_string)
            if not fteam_query or not fteam_query.elementA:
                raise BadRequestError(f"No valid query found: {fteam_q_string}")
            found_teams, _ = fantasy_team_service.search_fantasy_teams(fteam_query)
            if found_teams and len(found_teams) == 1:
                team = found_teams[0]
                fantasy_team = fantasy_team_service.update_fantasy_team(
                    team.id, FantasyTeamUpdate(**team_data)
                )
            elif len(found_teams) > 1:
                raise BadRequestError(
                    f"More than one bet found by search: {fteam_q_string}"
                )
            else:
                fantasy_team = fantasy_team_service.create_fantasy_team(
                    FantasyTeamCreate(**team_data)
                )

            players = []
            found_players = {}
            for player in row[2:10]:
                if not player:
                    raise BadRequestError(f"Player missing for team: {row.iloc[0]}")
                found_player_id = found_players.get(player)
                if found_player_id:
                    players.append(found_player_id)
                else:
                    users = user_service.find_by_name(player)
                    if not users or len(users) != 1:
                        raise BadRequestError(
                            f"Could not find player by name: {player}"
                        )
                    found_player = users[0]
                    found_players[found_player.name] = found_player.id
                    players.append(found_player.id)
            removePlayers = []
            for existingPlayer in fantasy_team.drafted_players:
                if not existingPlayer.id in players:
                    removePlayers.append(existingPlayer.id)

            fantasy_team_service.removeFantasyPlayers(fantasy_team.id, removePlayers)
            fantasy_team_service.addFantasyPlayers(fantasy_team.id, players)

        return Message(
            message="File uploaded successfully and data inserted into database"
        )
    else:
        raise BadRequestError("File type not allowed")


@router.post("/fantasy/import/bets", dependencies=[Depends(require_admin)])
def import_fantasy_bets(
    season_service: SeasonServiceDep,
    user_service: UserServiceDep,
    match_service: MatchServiceDep,
    series_service: SeriesServiceDep,
    fantasy_bet_service: FantasyBetServiceDep,
    file: Annotated[UploadFile | None, File()] = None,
    season_id: str | None = None,
    season_name: str | None = None,
) -> Message:
    """Import a xlsx with the information for a GNL fantasy season.

    Updates the database based on the import sheet.
    """
    if file is None:
        raise BadRequestError("No file part")

    season_id = int(season_id) if season_id else None

    if not season_id:
        if season_name:
            found_seasons = season_service.find_by_name(season_name)
            if not found_seasons:
                raise NotFoundError(f"Season could not be found by name: {season_name}")
            else:
                season_id = found_seasons[0].id
        else:
            raise BadRequestError(
                "Missing Season parameter, either season_id or season name is required"
            )

    if file.filename == "":
        raise BadRequestError("No selected file")
    if file and file.filename.endswith((".xlsx", ".xls")):
        # sheet_name=None reads both sheets, so the workbook is parsed once
        sheets = pd.read_excel(io.BytesIO(file.file.read()), sheet_name=None)

        df_bet_match = sheets["Betting Matches"]
        for index, row in df_bet_match.iterrows():
            if not cell_value(row.iloc[0]):
                continue
            week = row.iloc[0]
            q_string = f"playday=={week} and season_id=={season_id}"
            query = QueryUtil.parseQuery(q_string)
            if not query or not query.elementA:
                raise BadRequestError(f"No valid query found: {q_string}")
            matches = match_service.search(query)
            users = user_service.find_by_name(row.iloc[1])
            if not users or len(users) != 1:
                raise BadRequestError(
                    f"No or multiple users found for bet player[{row.iloc[1]}]: {users}"
                )
            player1 = users[0]
            users = user_service.find_by_name(row.iloc[2])
            if not users or len(users) != 1:
                raise BadRequestError(
                    f"No or multiple users found for bet player[{row.iloc[1]}]: {users}"
                )
            player2 = users[0]
            series = None
            if matches:
                for match in matches:
                    series_q_string = f"player1_id == {player1.id} and player2_id == {player2.id} and match_id == {match.id} or player1_id == {player2.id} and player2_id == {player1.id} and match_id == {match.id}"
                    series_query = QueryUtil.parseQuery(series_q_string)
                    if not query or not query.elementA:
                        raise BadRequestError(
                            f"No valid query found: {series_q_string}"
                        )
                    found_series = series_service.search(series_query)
                    if not found_series or len(found_series) != 1:
                        continue
                    series = found_series[0]
                    break
                if not series:
                    raise BadRequestError(
                        f"Could not identfy series for player: {row.iloc[1]}!"
                    )
            series_service.update_series(series.id, SeriesUpdate(is_fantasy_match=True))

        df_bets = sheets["Bets"]
        # One statement for the bets already stored, so the loop needs none
        stored_bets = fantasy_bet_service.bet_ids_of_season(season_id)
        for index, row in df_bets.iterrows():
            if not cell_value(row.iloc[0]):
                continue
            if not cell_value(row.iloc[0]):
                raise BadRequestError(f"Week not defined: {row.iloc[0]}")
            playday = row.iloc[0]

            if not cell_value(row.iloc[1]):
                raise BadRequestError(f"Captain not defined: {row.iloc[1]}")
            users = user_service.find_by_discord_tag(row.iloc[1])
            if not users or len(users) != 1:
                raise BadRequestError(
                    f"No or multiple users found for captain[{row.iloc[1]}]: {users}"
                )
            captain = users[0]

            if not cell_value(row.iloc[2]):
                raise BadRequestError(f"Bet Player not defined: {row.iloc[2]}")

            users = user_service.find_by_name(row.iloc[2])
            if not users or len(users) != 1:
                raise BadRequestError(
                    f"No or multiple users found for bet player[{row.iloc[2]}]: {users}"
                )
            bet_player = users[0]

            q_string = f"playday=={playday} and season_id=={season_id}"
            query = QueryUtil.parseQuery(q_string)
            if not query or not query.elementA:
                raise BadRequestError(f"No valid query found: {q_string}")
            matches = match_service.search(query)
            series = None
            if matches:
                for match in matches:
                    series_q_string = f"player1_id == {bet_player.id} and is_fantasy_match == True and match_id == {match.id} or player2_id == {bet_player.id} and is_fantasy_match == True and match_id == {match.id}"
                    series_query = QueryUtil.parseQuery(series_q_string)
                    if not query or not query.elementA:
                        raise BadRequestError(
                            f"No valid query found: {series_q_string}"
                        )
                    found_series = series_service.search(series_query)
                    if not found_series or len(found_series) != 1:
                        continue
                    series = found_series[0]
                    break
            if not series:
                raise BadRequestError(
                    f"Could not identfy series for player: {bet_player.name}!"
                )

            if not cell_value(row.iloc[3]):
                raise BadRequestError(f"Bet Points not defined: {row.iloc[3]}")

            bet_data = {
                "season_id": season_id,
                "series_id": series.id,
                "user_id": captain.id,
                "winner_id": bet_player.id,
                "bet_points": row.iloc[3],
            }

            key = (series.id, captain.id, bet_player.id)
            stored = stored_bets.get(key, [])
            if len(stored) == 1:
                fantasy_bet_service.update_fantasy_bet(
                    stored[0], FantasyBetUpdate(**bet_data)
                )
            elif len(stored) > 1:
                raise BadRequestError(f"More than one bet found by search: {key}")
            else:
                bet = fantasy_bet_service.create_fantasy_bet(
                    FantasyBetCreate(**bet_data)
                )
                # A later row of the same file must find the bet this one made
                stored_bets[key] = [bet.id]

        return Message(
            message="File uploaded successfully and data inserted into database"
        )
    else:
        raise BadRequestError("File type not allowed")
