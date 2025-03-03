import logging
from app import app
from flask import request, jsonify
from flask_jwt_extended import jwt_required
from custom_exceptions import NotFoundException
from flasgger import swag_from
from src.dtos.match_dto import MatchDTO

logger = logging.getLogger(__name__)

# Match endpoints
@app.route('/matches', methods=['POST'])
@swag_from({
    'summary': ' Add a new match',
    'description': 'Creates a new match between two teams with the given teams and score.',
    'tags': ['matches'],
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': MatchDTO.schema()
        }
    ],
    'responses': {
        201: {'description': 'Match created successfully'},
        500: {'description': 'Internal server error'}
    }
})
def add_match():
    try:
        data = request.json
        match = app.match_app_service.create_match(MatchDTO(data))
        return jsonify(match), 201
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/matches/<int:match_id>', methods=['PUT'])
@swag_from({
    'summary': 'Update a match',
    'description': 'Update the data of an existing matcht.',
    'tags': ['matches'],
    'parameters': [
        {'name': 'match_id', 'in': 'path', 'type': 'integer', 'required': True},
        {
            'name': 'body',
            'in': 'body',
            'required': False,
            'schema': MatchDTO.schema()
        }
    ],
    'responses': {
        200: {'description': 'Match updated successfully'},
        404: {'description': 'Match not found'},
        500: {'description': 'Internal server error'}
    }
})
def update_match(match_id):
    try:
        data = request.json
        match = app.match_app_service.update_match(match_id, score=data.get('score'))
        return jsonify(match)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/matches/<int:match_id>', methods=['DELETE'])
@swag_from({
    'summary': 'Delete a match',
    'description': 'Delete a match by its ID.',
    'tags': ['matches'],
    'parameters': [{'name': 'match_id', 'in': 'path', 'type': 'integer', 'required': True}],
    'responses': {
        204: {'description': 'Match deleted successfully'},
        500: {'description': 'Internal server error'}
    }
})
def delete_match(match_id):
    try:
        app.match_app_service.delete_match(match_id)
        return f"Match Deleted: {match_id}", 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/matches/<int:match_id>', methods=['GET'])
@swag_from({
    'summary': 'Get a match',
    'description': 'Retrieve a match by its ID.',
    'tags': ['matches'],
    'parameters': [{'name': 'match_id', 'in': 'path', 'type': 'integer', 'required': True}],
    'responses': {
        200: {'description': 'Match retrieved successfully'},
        404: {'description': 'Match not found'},
        500: {'description': 'Internal server error'}
    }
})
def get_match(match_id):
    try:
        match = app.match_app_service.get_match(match_id)
        return jsonify(match)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500