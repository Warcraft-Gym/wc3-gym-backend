import logging
from app import app
from flask import request, jsonify
from flask_jwt_extended import jwt_required
from custom_exceptions import NotFoundException

logger = logging.getLogger(__name__)

# User endpoints
@app.route('/users', methods=['POST'])
def add_user():
    try:
        data = request.json
        user = app.user_app_service.create_user(name=data['name'], email=data['email'])
        return jsonify(user), 201
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/users/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    try:
        data = request.json
        user = app.user_app_service.update_user(user_id, name=data.get('name'), email=data.get('email'))
        return jsonify(user)
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
        return jsonify(user)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500
