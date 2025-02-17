import logging
from app import app
from flask import request, jsonify, Response
from flask_jwt_extended import jwt_required
from custom_exceptions import NotFoundException
from flasgger import swag_from
from src.dtos.team_dto import TeamDTO
import enum
import json

logger = logging.getLogger(__name__)

class EnumEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, enum.Enum):
            return obj.value
        return json.JSONEncoder.default(self, obj)

# Team endpoints
@app.route('/teams', methods=['POST'])
@swag_from({
    'summary': 'Add a new team',
    'description': 'Create a new team with the provided name.',
    'tags': ['teams'],
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': TeamDTO.schema()
        }
    ],
    'responses': {
        201: {'description': 'Team created successfully'},
        500: {'description': 'Internal server error'}
    }
})
def add_team():
    try:
        data = request.json
        team = app.team_app_service.create_team(TeamDTO(data))
        json_data = json.dumps(team, cls=EnumEncoder)
        return Response(json_data, status=201, content_type='application/json')
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/teams/<int:team_id>', methods=['PUT'])
@swag_from({
    'summary': 'Update a team',
    'description': 'Update the name of an existing team.',
    'tags': ['teams'],
    'parameters': [
        {'name': 'team_id', 'in': 'path', 'type': 'integer', 'required': True},
        {
            'name': 'body',
            'in': 'body',
            'required': False,
            'schema': TeamDTO.schema()
        }
    ],
    'responses': {
        200: {'description': 'Team updated successfully'},
        404: {'description': 'Team not found'},
        500: {'description': 'Internal server error'}
    }
})
def update_team(team_id):
    try:
        data = request.json
        team = app.team_app_service.update_team(team_id, name=data.get('name'))
        json_data = json.dumps(team, cls=EnumEncoder)
        return Response(json_data, status=200, content_type='application/json')
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/teams/<int:team_id>', methods=['DELETE'])
@swag_from({
    'summary': 'Delete a team',
    'description': 'Delete a team by its ID.',
    'tags': ['teams'],
    'parameters': [{'name': 'team_id', 'in': 'path', 'type': 'integer', 'required': True}],
    'responses': {
        204: {'description': 'Team deleted successfully'},
        500: {'description': 'Internal server error'}
    }
})
def delete_team(team_id):
    try:
        app.team_app_service.delete_team(team_id)
        return f"Team Deleted: {team_id}", 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/teams/<int:team_id>', methods=['GET'])
@swag_from({
    'summary': 'Get a team',
    'description': 'Retrieve a team by its ID.',
    'tags': ['teams'],
    'parameters': [{'name': 'team_id', 'in': 'path', 'type': 'integer', 'required': True}],
    'responses': {
        200: {'description': 'Team retrieved successfully'},
        404: {'description': 'Team not found'},
        500: {'description': 'Internal server error'}
    }
})
def get_team(team_id):
    try:
        team = app.team_app_service.get_team(team_id)
        json_data = json.dumps(team, cls=EnumEncoder)
        return Response(json_data, status=200, content_type='application/json')
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/teams/addPlayer/<int:team_id>', methods=['POST'])
@swag_from({
    'summary': 'Add players to a team',
    'description': 'Add players to a team using their IDs.',
    'tags': ['teams'],
    'parameters': [
        {'name': 'team_id', 'in': 'path', 'type': 'integer', 'required': True},
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'player_ids': {'type': 'array', 'items': {'type': 'integer'}}
                },
                'required': ['player_ids']
            }
        }
    ],
    'responses': {
        200: {'description': 'Players added successfully'},
        404: {'description': 'Team not found'},
        500: {'description': 'Internal server error'}
    }
})
def addPlayer(team_id):
    try:
        data = request.json
        team = app.team_app_service.addPlayers(team_id, data.get("player_ids"))
        json_data = json.dumps(team, cls=EnumEncoder)
        return Response(json_data, status=200, content_type='application/json')
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500
