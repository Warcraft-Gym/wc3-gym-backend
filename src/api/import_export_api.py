import logging
from app import app
from flask import request, jsonify, send_file
from flask_jwt_extended import jwt_required
from custom_exceptions import NotFoundException
from flasgger import swag_from
from src.dtos.season_dto import SeasonDTO
import pandas as pd
import io
from io import BytesIO
import openpyxl
from src.util.import_util import ImportUtil
from src.dtos.user_dto import UserDTO
from src.dtos.team_dto import TeamDTO
from src.util.query_util import QueryUtil

logger = logging.getLogger(__name__)

# import export endpoints
@app.route('/import', methods=['POST'])
@swag_from({
    'summary': 'Import a google spreadsheet with the information for a GNL season',
    'description': 'Updates the database based on the import sheet',
    'tags': ['import export'],
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
        if file and file.filename.endswith(('.xlsx', '.xls')):
            file_stream = io.BytesIO(file.read())
            
            # Load the Google Sheet into a DataFrame
            df = pd.read_excel(file_stream, sheet_name=None)
            players = df.get('Players')

            teams = []
            teams_players = {}

            for index, row in players.iterrows():
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
                    user = app.user_app_service.update_user(users[0].get('id'), UserDTO(user_data))
                

                team_name = ImportUtil.isNa(row['Team Abbr'])
                if team_name and not teams_players.get(team_name):
                    team_data = {
                        'name' : ImportUtil.isNa(row['Team Abbr'])
                    }
                    teams.append(team_data)
                    teams_players[team_name] = [user.get('id')]
                elif team_name:
                    players = teams_players.get(team_name)
                    players.append(user.get('id'))

            team_ids = []
            for team_data in teams:
                query = QueryUtil.parseQuery("name == " +  team_data.get('name'))
                if not query or not query.elementA:
                    raise Exception(f"No valid query found: {"name == " +  team_data.get('name')}")
                found_teams = app.team_app_service.search(query)
                team = None
                if not found_teams:
                    team = app.team_app_service.create_team(TeamDTO(team_data))
                else:
                    team = app.team_app_service.update_team(found_teams[0].get('id'), TeamDTO(team_data))
                team_ids.append(team.get('id'))
                players = teams_players.get(team_data.get('name'))
                app.team_app_service.addPlayers(team.get('id'), players)
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
                    season_id = app.season_app_service.create_season(SeasonDTO(season_data)).get('id')
                else: 
                    season_id = found_seasons[0].get('id')
                
            app.season_app_service.addTeams(season_id, team_ids)
            
            
            matches = df.get('Matches')

            
            return jsonify({"message": "File uploaded successfully and data inserted into database"}), 200
        else:
            return jsonify({"error": "File type not allowed"}), 400
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@app.route('/export', methods=['POST'])
@swag_from({
    'summary': 'Export a google spreadsheet with the information for a GNL season',
    'description': 'Export an exel sheet with the data of one season',
    'tags': ['import export'],
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
        season_id = request.args.get('season_id')
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
                season_id = season.get('id')


        query = QueryUtil.parseQuery(f"season_id == {season_id}")
        if not query or not query.elementA:
            raise Exception(f"No valid query found: season_id == {season_id}")
        season_teams = app.team_app_service.search(query)
        player_team_map = {}
        for team in season_teams:
            for player in team.get('player'):
                player_team_map[player.get('name')] = team.get('name')

        workbook = openpyxl.Workbook()
        # Create worksheets
        user_sheet = workbook.create_sheet(title='Players')
        users = app.user_app_service.getAll()
        user_sheet.append(['Bnet', 'Bnet (no ID)', 'Bnet + Host', 'Discord', 'Race', 'Team Abbr', 'MMR', 'Country'])
        for user in users:
            season_team = player_team_map.get(user.get('name'))
            if season_team:
                user_sheet.append([user.get('battleTag'),user.get('name'),f"{user.get('name')}*",user.get('discordTag'),ImportUtil.getRaceNameString(user.get('race')),season_team, user.get('mmr'),ImportUtil.getCountryNameString(user.get('country'))])

        excel_stream = BytesIO()
        workbook.save(excel_stream)
        excel_stream.seek(0)

        # Return the Excel file for download
        return send_file(
            excel_stream,
            as_attachment=True,
            download_name=f'{season.get('name')}.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500