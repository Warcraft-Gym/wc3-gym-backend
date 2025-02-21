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
from src.util.query_util import QueryUtil

logger = logging.getLogger(__name__)

# season endpoints
@app.route('/import/<int:season_id>', methods=['POST'])
@swag_from({
    'summary': 'Import a google spreadsheet with the information for a GNL season',
    'description': 'Updates the database based on the import sheet',
    'tags': ['import export'],
    'parameters': [
        {'name': 'season_id', 'in': 'path', 'type': 'integer', 'required': True},
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
def import_season(season_id):
    try:
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
            for index, row in players.iterrows():
                data = {
                        'name': row['Bnet (no ID)'],
                        'battleTag': row['Bnet'],
                        'discordTag': row['Discord'],
                        'race': ImportUtil.getRaceEnumString(row['Race']),
                        'mmr': None if pd.isna(row['MMR']) else row['MMR'],
                        'country':   ImportUtil.getCountryEnumString(row['Country'])
                    }
                query = QueryUtil.parseQuery("battleTag == " +  data.get('battleTag'))
                if not query or not query.elementA:
                    raise Exception(f"No valid query found: {"battleTag == " +  data.get('battleTag')}")
                users = app.user_app_service.search(query)
                if not users:
                    app.user_app_service.create_user(UserDTO(data))
                else:
                    app.user_app_service.update_user(users[0].get('id'), UserDTO(data))
            
            teams = df.get('Player Team Assignment')
            matches = df.get('Matches')

            
            return jsonify({"message": "File uploaded successfully and data inserted into database"}), 200
        else:
            return jsonify({"error": "File type not allowed"}), 400
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500
