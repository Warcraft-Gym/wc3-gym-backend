import logging
from app import app
from flask import request, jsonify
from flask_jwt_extended import jwt_required
from custom_exceptions import NotFoundException
from flasgger import swag_from
from src.dtos.season_dto import SeasonDTO

logger = logging.getLogger(__name__)

# season endpoints
@app.route('/season', methods=['POST'])
@swag_from({
    'summary': 'Add a new season',
    'description': 'Create a new season with the provided name.',
    'tags': ['seasons'],
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': SeasonDTO.schema()
        }
    ],
    'responses': {
        201: {'description': 'Season created successfully'},
        500: {'description': 'Internal server error'}
    }
})
def add_season():
    try:
        data = request.json
        season = app.season_app_service.create_season(SeasonDTO(data))
        return jsonify(season), 201
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/seasons/<int:season_id>', methods=['PUT'])
@swag_from({
    'summary': 'Update a season',
    'description': 'Update the name of an existing season.',
    'tags': ['seasons'],
    'parameters': [
        {'name': 'season_id', 'in': 'path', 'type': 'integer', 'required': True},
        {
            'name': 'body',
            'in': 'body',
            'required': False,
            'schema': SeasonDTO.schema()
        }
    ],
    'responses': {
        200: {'description': 'season updated successfully'},
        404: {'description': 'season not found'},
        500: {'description': 'Internal server error'}
    }
})
def update_season(season_id):
    try:
        data = request.json
        season = app.season_app_service.update_season(season_id, name=data.get('name'))
        return jsonify(season)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/seasons/<int:season_id>', methods=['DELETE'])
@swag_from({
    'summary': 'Delete a season',
    'description': 'Delete a season by its ID.',
    'tags': ['seasons'],
    'parameters': [{'name': 'season_id', 'in': 'path', 'type': 'integer', 'required': True}],
    'responses': {
        204: {'description': 'season deleted successfully'},
        500: {'description': 'Internal server error'}
    }
})
def delete_season(season_id):
    try:
        app.season_app_service.delete_season(season_id)
        return f"season Deleted: {season_id}", 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/seasons/<int:season_id>', methods=['GET'])
@swag_from({
    'summary': 'Get a season',
    'description': 'Retrieve a season by its ID.',
    'tags': ['seasons'],
    'parameters': [{'name': 'season_id', 'in': 'path', 'type': 'integer', 'required': True}],
    'responses': {
        200: {'description': 'season retrieved successfully'},
        404: {'description': 'season not found'},
        500: {'description': 'Internal server error'}
    }
})
def get_season(season_id):
    try:
        season = app.season_app_service.get_season(season_id)
        return jsonify(season)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@app.route('/season/addTeams/<int:season_id>', methods=['POST'])
@swag_from({
    'summary': 'Add teams to season',
    'description': 'Add teams to season by providing a list of team ids.',
    'tags': ['seasons'],
    'parameters': [
        {'name': 'season_id', 'in': 'path', 'type': 'integer', 'required': True},
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'team_ids': {'type': 'array', 'items': {'type': 'integer'}}
                },
                'required': ['team_ids']
            }
        }],
    'responses': {
        200: {'description': 'Added teams to season successfully'},
        404: {'description': 'Season or Teams not found'},
        500: {'description': 'Internal server error'}
    }
})
def add_teams(season_id):
    try:
        data = request.json
        season = app.season_app_service.addTeams(season_id, data.get("team_ids"))
        return jsonify(season)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/season/removeTeams/<int:season_id>', methods=['POST'])
@swag_from({
    'summary': 'Remove teams from season',
    'description': 'Remove teams from season by providing a list of team ids.',
    'tags': ['seasons'],
    'parameters': [
        {'name': 'season_id', 'in': 'path', 'type': 'integer', 'required': True},
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'team_ids': {'type': 'array', 'items': {'type': 'integer'}}
                },
                'required': ['team_ids']
            }
        }],
    'responses': {
        200: {'description': 'Removed teams from season successfully'},
        404: {'description': 'Season or Teams not found'},
        500: {'description': 'Internal server error'}
    }
})
def remove_teams(season_id):
    try:
        data = request.json
        season = app.season_app_service.removeTeams(season_id, data.get("team_ids"))
        return jsonify(season)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500