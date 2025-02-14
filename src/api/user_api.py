import logging
from app import app
from flask import request, jsonify, Response
from flask_jwt_extended import jwt_required
from custom_exceptions import NotFoundException
from src.dtos.user_dto import UserDTO
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
    try:
        app.user_app_service.delete_user(user_id)
        return f"Team Deleted: {user_id}", 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@app.route('/users/<int:user_id>', methods=['GET'])
def get_user(user_id):
    try:
        user = app.user_app_service.get_user(user_id)
        json_data = json.dumps(user, cls=EnumEncoder)
        return Response(json_data, status=201, content_type='application/json')
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500
