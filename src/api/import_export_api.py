import logging
from app import app
from datetime import datetime
from flask import request, jsonify, send_file
from flask_jwt_extended import jwt_required
from custom_exceptions import NotFoundException
from flasgger import swag_from
from src.dtos.season_dto import SeasonDTO
from src.dtos.user_dto import UserDTO
from src.dtos.team_dto import TeamDTO
from src.dtos.series_dto import SeriesDTO
from src.dtos.match_dto import MatchDTO
import pandas as pd
import io
from io import BytesIO
import openpyxl
from src.util.import_util import ImportUtil


from src.util.query_util import QueryUtil

logger = logging.getLogger(__name__)

# import export endpoints
@app.route('/import', methods=['POST'])
@jwt_required()
@swag_from({
    'summary': 'Import a google spreadsheet with the information for a GNL season',
    'description': 'Updates the database based on the import sheet',
    'tags': ['import export'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'season_id', 'in': 'query', 'type': 'integer', 'required': False},
        {'name': 'season_name', 'in': 'query', 'type': 'string', 'required': False},
        {
            'name': 'file',
            'in': 'formData',
            'type': 'file',
            'required': True,
            'description': 'File to be uploaded (Google Sheet)'
        }
    ],
    'consumes': [
        'multipart/form-data'
    ],
    'responses': {
        200: {'description': 'Season updated successfully'},
        400: {
            'description': 'Bad Request',
            'examples': {
                'application/json': {
                    'error': 'No file part'
                }
            }
        },
        500: {'description': 'Internal server error'}
    }
})
def import_season():
    try:
        season_id = request.args.get('season_id')
        season_name = request.args.get('season_name')
        if 'file' not in request.files:
            return jsonify({"error": "No file part"}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No selected file"}), 400
        player_name_id = {}
        if file and file.filename.endswith(('.xlsx', '.xls')):
            file_stream = io.BytesIO(file.read())
            
            # Load the Google Sheet into a DataFrame
            df_players = pd.read_excel(file_stream, sheet_name='Players')

            teams = []
            teams_players = {}
            for index, row in df_players.iterrows():
                user_data = {
                        'name': ImportUtil.isNa(row['Bnet (no ID)']),
                        'battleTag': ImportUtil.isNa(row['Bnet']),
                        'discordTag': ImportUtil.isNa(row['Discord']),
                        'race': ImportUtil.getRaceEnumString(ImportUtil.isNa(row['Race'])),
                        'mmr': ImportUtil.isNa(row['MMR']),
                        'country':   ImportUtil.getCountryEnumString(ImportUtil.isNa(row['Country']))
                    }


                query = QueryUtil.parseQuery("battleTag == " +  user_data.get('battleTag'))
                if not query or not query.elementA:
                    raise Exception(f"No valid query found: {"battleTag == " +  user_data.get('battleTag')}")
                users = app.user_app_service.search(query)
                user = None
                if not users:
                    user = app.user_app_service.create_user(UserDTO(user_data))
                else:
                    user = app.user_app_service.update_user(users[0].id, UserDTO(user_data))
                player_name_id[user.name] = user.id

                team_name = ImportUtil.isNa(row['Team Abbr'])
                if team_name and not teams_players.get(team_name):
                    team_data = {
                        'name' : ImportUtil.isNa(row['Team Abbr'])
                    }
                    teams.append(team_data)
                    teams_players[team_name] = [user.id]
                elif team_name:
                    players = teams_players.get(team_name)
                    players.append(user.id)
                    
            season_data = {
                'name' : season_name
            }
            if season_id and season_name:
                app.season_app_service.update_season(season_id, SeasonDTO(season_data))
            elif season_name:
                query = QueryUtil.parseQuery("name == " +  season_name)
                if not query or not query.elementA:
                    raise Exception(f"No valid query found: {"name == " +  season_name}")
                found_seasons = app.season_app_service.search(query)
                if not found_seasons:
                    season_id = app.season_app_service.create_season(SeasonDTO(season_data)).id
                else: 
                    season_id = found_seasons[0].id
            
            team_ids = []
            team_name_id = {}
            for team_data in teams:
                query = QueryUtil.parseQuery("name == " +  team_data.get('name'))
                if not query or not query.elementA:
                    raise Exception(f"No valid query found: {"name == " +  team_data.get('name')}")
                found_teams = app.team_app_service.search(query)
                team = None
                if not found_teams:
                    team = app.team_app_service.create_team(TeamDTO(team_data))
                else:
                    team = app.team_app_service.update_team(found_teams[0].id, TeamDTO(team_data))
                team_name_id[team.name] = team.id
                team_ids.append(team.id)
                players = teams_players.get(team.name)
                app.team_app_service.addPlayers(team.id, season_id, players)

            app.season_app_service.addTeams(season_id, team_ids)
            
            excel_file = pd.ExcelFile(file_stream)
            sheet_names = excel_file.sheet_names
            week_sheets = [name for name in sheet_names if name.lower().startswith("week")]

            # Count the number of "Week" sheets
            number_of_week_sheets = len(week_sheets)

            for i in range(1,number_of_week_sheets+1):
                week = pd.read_excel(file_stream, sheet_name=f"Week {i}", header=None)
                matchups_rows = []
                for index, row in week.iterrows():
                    if "VS" in row.values:
                        matchups_rows.append(index)
                matchups_rows.append(len(week))
                for start, end in zip(matchups_rows, matchups_rows[1:]): 
                    team1 = None
                    team2 = None
                    match = None
                    for index, row in week.iloc[start:end].iterrows():
                        if index == start:
                            team1 = ImportUtil.isNa(row[0])
                            team2 = ImportUtil.isNa(row[2])
                            if not team1 or not team2:
                                raise Exception('Team 1 or Team 2 not properly identified in row:]')
                            team1_id = team_name_id[team1]
                            team2_id = team_name_id[team2]
                            q_string = f"team1_id=={team1_id} and team2_id=={team2_id} and season_id=={season_id}"
                            query = QueryUtil.parseQuery(q_string)
                            if not query or not query.elementA:
                                raise Exception(f"No valid query found: {q_string}")
                            found_matches = app.match_app_service.search(query)
                            if not found_matches:
                                match_data = {
                                    'team1_id': team1_id,
                                    'team2_id': team2_id,
                                    'season_id': season_id,
                                    'playday': i
                                }
                                match = app.match_app_service.create_match(MatchDTO(match_data))
                            else:
                                match = found_matches[0]
                            continue
                        if "Date" in row.values:
                            continue
                        if pd.isnull(row[5]) or pd.isnull(row[8]):
                            continue
                        if not team1 or not team2:
                            raise Exception(f"Teams could not be identified for Week {i} and row range {start}/{end}")
                        
                        player1_id = player_name_id[row[5].rstrip("*")]
                        player2_id = player_name_id[row[8].rstrip("*")]
                        date_time = None
                        if ImportUtil.isNa(row[4]) and ImportUtil.isNa(row[3]):
                            date_time = datetime.combine(row[4], row[3])
                        series_data = {
                            'caster': ImportUtil.isNa(row[1]),
                            'date_time': date_time,
                            'match_id' : match.id,
                            'player1_id': player1_id,
                            'player1_score': ImportUtil.isNa(row[6]),
                            'player2_score': ImportUtil.isNa(row[7]),
                            'player2_id': player2_id
                        }
                        series_q_string = f"match_id=={match.id} and player1_id=={player1_id} and player2_id=={player2_id}"
                        series_query = QueryUtil.parseQuery(series_q_string)
                        if not query or not query.elementA:
                            raise Exception(f"No valid query found: {series_q_string}")
                        found_series = app.series_app_service.search(series_query)
                        if not found_series:
                            series = app.series_app_service.create_series(SeriesDTO(series_data))
                        else:
                            series = found_series[0]
                            series = app.series_app_service.update_series(series.id, SeriesDTO(series_data))                       

            
            return jsonify({"message": "File uploaded successfully and data inserted into database"}), 200
        else:
            return jsonify({"error": "File type not allowed"}), 400
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@app.route('/export', methods=['POST'])
@jwt_required()
@swag_from({
    'summary': 'Export a google spreadsheet with the information for a GNL season',
    'description': 'Export an exel sheet with the data of one season',
    'tags': ['import export'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'season_id', 'in': 'query', 'type': 'integer', 'required': False},
        {'name': 'season_name', 'in': 'query', 'type': 'string', 'required': False}
    ],
    'responses': {
        200: {
            'description': 'A downloadable Excel file with user and team information',
            'content': {
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': {
                    'schema': {
                        'type': 'string',
                        'format': 'binary'
                    }
                }
            }
        },
        500: {'description': 'Internal server error'}
    }
})
def exort_season():
    try:
        season_id = int(request.args.get('season_id'))
        season_name = request.args.get('season_name')
        season_teams = []
        season = None
        if season_id:
            season = app.season_app_service.get_season(season_id)
            if not season:
                raise NotFoundException(f"season not found by id: {season_id}")
        elif not season_id and season_name:
            query = QueryUtil.parseQuery(f"name == {season_name}")
            if not query or not query.elementA:
                raise Exception(f"No valid query found: name == {season_name}")
            found_seasons = app.season_app_service.search(query)
            if not found_seasons:
                raise NotFoundException(f"season not found by name: {season_name}")
            else: 
                season = found_seasons[0]
                season_id = season.id


        workbook = openpyxl.Workbook()
        default_sheet = workbook.active
        workbook.remove(default_sheet)
        # Create worksheets
        ranking_sheet = workbook.create_sheet(title='Ranking')
        user_sheet = workbook.create_sheet(title='Players')
        user_sheet.append(['Bnet', 'Bnet (no ID)', 'Bnet + Host', 'Discord', 'Race', 'Team Abbr', 'MMR', 'Country'])
        player_team_sheet = workbook.create_sheet(title='Player Team Assignment')
        player_team_sheet.append(['battle net name', 'team'])
        player_website_sheet = workbook.create_sheet(title='Player Website')
        player_website_sheet.append(['player', 'race_image', 'w3_champions_profile', 'mmr', 'country', 'team', 'captain'])
        ranking_sheet.append([f"{season.name} Rankings"])
        ranking_sheet.append([""])
        ranking_header = []
        ranking_header.append('Rank')
        ranking_header.append('Team')
        for number in range(season.number_weeks):
            ranking_header.append(f"Week {number}")
        ranking_header.append('Points')
        ranking_header.append('Points Against (PA)')
        ranking_header.append('Points Available')
        ranking_sheet.append(ranking_header)
        rank = 1

        season_teams = app.team_app_service.get_teams_season(season_id)
        for team in season_teams:
            # ranking sheet
            team_rank = []
            team_rank.append(rank)
            team_rank.append(team.name)
            for number in range(season.number_weeks):
                team_rank.append(0)
            team_rank.append(team.seasons_info[0].final_score)
            team_rank.append(team.seasons_info[0].points_available)
            team_rank.append(team.seasons_info[0].points_against)
            ranking_sheet.append(team_rank)
            rank += 1
            # Player sheet
            players = team.player_by_season[season_id]
            for user in players:
                player_team_sheet.append([user.battleTag,team.name])
                player_website_sheet.append([user.name, ImportUtil.getRaceImage(user.race),ImportUtil.getW3ChampionURL(user.battleTag),user.mmr,ImportUtil.getCountryNameString(user.country),team.name])
                user_sheet.append([user.battleTag, user.name,f"{user.name}*",user.discordTag,ImportUtil.getRaceNameString(user.race),team.name, user.mmr,ImportUtil.getCountryNameString(user.country)])
                
        excel_stream = BytesIO()
        workbook.save(excel_stream)
        excel_stream.seek(0)

        # Return the Excel file for download
        return send_file(
            excel_stream,
            as_attachment=True,
            download_name=f'{season.name}.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500