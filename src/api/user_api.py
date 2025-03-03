import logging
from app import app
from flask import request, jsonify, Response
from flask_jwt_extended import jwt_required, get_jwt_identity
from custom_exceptions import NotFoundException
from src.dtos.user_dto import UserDTO
from src.util.query_util import QueryUtil
import enum
import json
from flasgger import swag_from

logger = logging.getLogger(__name__)

class EnumEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, enum.Enum):
            return obj.value
        return json.JSONEncoder.default(self, obj)

# Configure Flask to use the custom JSON encoder
app.json_encoder = EnumEncoder

# User endpoints
@app.route('/users', methods=['POST'])
@jwt_required()
@swag_from({
    'summary': 'Add a new user',
    'description': 'Create a new user with the provided details.',
    'tags': ['users'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': UserDTO.schema()
        }
    ],
    'responses': {
        201: {'description': 'User created successfully'},
        500: {'description': 'Internal server error'}
    }
})
def add_user():
    try:
        data = request.json
        user = app.user_app_service.create_user(UserDTO(data))
        if(user):
            user = user.to_dict()
        json_data = json.dumps(user, cls=EnumEncoder)
        return Response(json_data, status=201, content_type='application/json')
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/users/<int:user_id>', methods=['PUT'])
@jwt_required()
@swag_from({
    'summary': 'Update an existing user',
    'description': 'Update the details of an existing user.',
    'tags': ['users'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'user_id', 'in': 'path', 'type': 'integer', 'required': True, 'description': 'The ID of the user to update'},
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': UserDTO.schema()
        }
    ],
    'responses': {
        201: {'description': 'User updated successfully'},
        404: {'description': 'User not found'},
        500: {'description': 'Internal server error'}
    }
})
def update_user(user_id):
    try:
        data = request.json
        user = app.user_app_service.update_user(user_id, UserDTO(data))
        if(user):
            user = user.to_dict()
        json_data = json.dumps(user, cls=EnumEncoder)
        return Response(json_data, status=201, content_type='application/json')
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/users/<int:user_id>', methods=['DELETE'])
@jwt_required()
@swag_from({
    'summary': 'Delete an existing user',
    'description': 'Delete a user by their ID.',
    'tags': ['users'],
    'security': [{'BearerAuth': []}],
    'parameters': [{'name': 'user_id', 'in': 'path', 'type': 'integer', 'required': True, 'description': 'The ID of the user to delete'}],
    'responses': {
        204: {'description': 'User deleted successfully'},
        500: {'description': 'Internal server error'}
    }
})
def delete_user(user_id):
    try:
        app.user_app_service.delete_user(user_id)
        return f"User Deleted: {user_id}", 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/users/<int:user_id>', methods=['GET'])
@swag_from({
    'summary': 'Get a user by ID',
    'description': 'Retrieve a user by their ID.',
    'tags': ['users'],
    'parameters': [{'name': 'user_id', 'in': 'path', 'type': 'integer', 'required': True, 'description': 'The ID of the user to retrieve'}],
    'responses': {
        200: {'description': 'User retrieved successfully'},
        404: {'description': 'User not found'},
        500: {'description': 'Internal server error'}
    }
})
def get_user(user_id):
    try:
        user = app.user_app_service.get_user(user_id)
        if(user):
            user = user.to_dict()
        json_data = json.dumps(user, cls=EnumEncoder)
        return Response(json_data, status=200, content_type='application/json')
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/users', methods=['GET'])
@swag_from({
    'summary': 'Get all users',
    'description': 'Retrieve all users.',
    'tags': ['users'],
    'responses': {
        200: {'description': 'Users retrieved successfully'},
        404: {'description': 'Users not found'},
        500: {'description': 'Internal server error'}
    }
})
def get_AllUser():
    try:
        users = app.user_app_service.getAll()
        out = []
        if(users):
            for user in users:
                out.append(user.to_dict())
        json_data = json.dumps(out, cls=EnumEncoder)
        return Response(json_data, status=200, content_type='application/json')
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/users/search', methods=['POST'])
@swag_from({
    'summary': 'Search users by criteria',
    'description': 'Search users by criteria using a custom query format.',
    'tags': ['users'],
    'parameters': [
        {
            'name': 'query',
            'in': 'query',
            'type': 'string',
            'required': False,
            'description': '''
                Search criteria in the following format
                and | or conditions are supported but no brackets

                key operator value and key operator value

                e.g.:
                name ilike xxxx or id == 12
                Operators supported: ==, !=, >, >=, <, <=, ilike
            '''
        }
    ],
    'responses': {
        200: {'description': 'Users retrieved successfully'},
        404: {'description': 'Users not found'},
        500: {'description': 'Internal server error'}
    }
})
def search_users():
    try:
        query_param = request.args.get('query', '')
        query = QueryUtil.parseQuery(query_param)
        if not query or not query.elementA:
            raise Exception(f"No valid query found: {query_param}")
        users = app.user_app_service.search(query)
        out = []
        if(users):
            for user in users:
                out.append(user.to_dict())
        json_data = json.dumps(out, cls=EnumEncoder)
        return Response(json_data, status=200, content_type='application/json')
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500
