import logging
from app import app
from flask import request, jsonify
from flask_jwt_extended import jwt_required
from custom_exceptions import NotFoundException

logger = logging.getLogger(__name__)


# Team endpoints
@app.route('/teams', methods=['POST'])
def add_team():
    try:
        data = request.json
        team = app.team_app_service.create_team(name=data['name'])
        return jsonify(team), 201
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/teams/<int:team_id>', methods=['PUT'])
def update_team(team_id):
    try:
        data = request.json
        team = app.team_app_service.update_team(team_id, name=data.get('name'))
        return jsonify(team)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/teams/<int:team_id>', methods=['DELETE'])
def delete_team(team_id):
    try:
        app.team_app_service.delete_team(team_id)
        return f"Team Deleted: {team_id}", 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/teams/<int:team_id>', methods=['GET'])
def get_team(team_id):
    try:
        team = app.team_app_service.get_team(team_id)
        return jsonify(team)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500
