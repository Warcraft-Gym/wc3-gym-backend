import logging
from app import app
from flask import request, jsonify
from flask_jwt_extended import jwt_required
from custom_exceptions import NotFoundException
from flasgger import swag_from
from src.dtos.season_dto import SeasonDTO
import pandas as pd
import io
from src.util.import_util import ImportUtil
from src.dtos.user_dto import UserDTO
from src.dtos.team_dto import TeamDTO
from src.util.query_util import QueryUtil

logger = logging.getLogger(__name__)

# season endpoints
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
