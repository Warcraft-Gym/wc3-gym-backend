import logging
from app import app
from flask import request, jsonify, Response
from custom_exceptions import NotFoundException
from src.dtos.user_dto import UserDTO
from src.util.query_util import QueryUtil
import enum
import json

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
def add_user():
    """
    Add a new user
    ---
    tags:
      - users
    parameters:
      - name: body
        in: body
        required: true
        schema:
          $ref: '#/definitions/UserDTO'
    responses:
      201:
        description: User created successfully
      500:
        description: Internal server error
    """
    try:
        data = request.json
        user = app.user_app_service.create_user(UserDTO(data))
        json_data = json.dumps(user, cls=EnumEncoder)
        return Response(json_data, status=201, content_type='application/json')
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/users/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    """
    Update an existing user
    ---
    tags:
      - users
    parameters:
      - name: user_id
        in: path
        type: integer
        required: true
        description: The ID of the user to update
      - name: body
        in: body
        required: true
        schema:
          $ref: '#/definitions/UserDTO'
    responses:
      201:
        description: User updated successfully
      404:
        description: User not found
      500:
        description: Internal server error
    """
    try:
        data = request.json
        userdto = UserDTO(data)
        userdto.id = user_id
        user = app.user_app_service.update_user(userdto)
        json_data = json.dumps(user, cls=EnumEncoder)
        return Response(json_data, status=201, content_type='application/json')
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    """
    Delete an existing user
    ---
    tags:
      - users
    parameters:
      - name: user_id
        in: path
        type: integer
        required: true
        description: The ID of the user to delete
    responses:
      204:
        description: User deleted successfully
      500:
        description: Internal server error
    """
    try:
        app.user_app_service.delete_user(user_id)
        return f"Team Deleted: {user_id}", 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@app.route('/users/<int:user_id>', methods=['GET'])
def get_user(user_id):
    """
    Get a user by ID
    ---
    tags:
      - users
    parameters:
      - name: user_id
        in: path
        type: integer
        required: true
        description: The ID of the user to retrieve
    responses:
      201:
        description: User retrieved successfully
      404:
        description: User not found
      500:
        description: Internal server error
    """
    try:
        logger.debug("users - GET: " + user_id)
        user = app.user_app_service.get_user(user_id)
        json_data = json.dumps(user, cls=EnumEncoder)
        return Response(json_data, status=201, content_type='application/json')
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/users', methods=['GET'])
def get_AllUser():
    """
    Get all users
    ---
    tags:
      - users
    responses:
      201:
        description: Users retrieved successfully
      404:
        description: Users not found
      500:
        description: Internal server error
    """
    try:
        users = app.user_app_service.getAll()
        json_data = json.dumps(users, cls=EnumEncoder)
        return Response(json_data, status=201, content_type='application/json')
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/search_users', methods=['POST'])
def search_users():
    """
    Search users by criteria
    ---
    tags:
      - users
    parameters:
      - name: query
        in: query
        type: string
        required: false
        description: |
          Search criteria in the following format
          and | or conditions are supported but no brackets

          key operator value and key operator value
          
          e.g.:
          name ilike xxxx or id == 12
          Operators supported: ==, !=, >, >=, <, <=, ilike)
    responses:
      201:
        description: Users retrieved successfully
      404:
        description: Users not found
      500:
        description: Internal server error
    """
    try:
        query_param = request.args.get('query', '')
        query = QueryUtil.parseQuery(query_param)
        if not query or not query.elementA:
          raise Exception(f"No valid query found: {query_param}")
        users = app.user_app_service.search(query)
        json_data = json.dumps(users, cls=EnumEncoder)
        return Response(json_data, status=201, content_type='application/json')
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500