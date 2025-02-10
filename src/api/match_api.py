import logging
from app import app
from flask import request, jsonify
from flask_jwt_extended import jwt_required
from custom_exceptions import NotFoundException

logger = logging.getLogger(__name__)

# Match endpoints
@app.route('/matches', methods=['POST'])
def add_match():
    try:
        data = request.json
        match = app.match_app_service.create_match(team1_id=data['team1_id'], team2_id=data['team2_id'], score=data['score'])
        return jsonify(match), 201
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/matches/<int:match_id>', methods=['PUT'])
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
def delete_match(match_id):
    try:
        app.match_app_service.delete_match(match_id)
        return f"Match Deleted: {match_id}", 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/matches/<int:match_id>', methods=['GET'])
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